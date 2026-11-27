using System.Text;
using System.Text.RegularExpressions;

namespace AgentTools.Hosts.Tests.Architecture;

public static class SelfStart
{
    private static readonly string[] Markers =
    [
        "Environment.ProcessPath",
        "Environment.GetCommandLineArgs",
        "Process.GetCurrentProcess",
        "Assembly.GetEntryAssembly",
        "\"agent-tools\"",
    ];

    // The own-path members of the types above, for a file that reaches them through `using static`
    // or an alias without the type name.
    private static readonly (string Type, string[] Members)[] MarkerTypes =
    [
        ("Environment", ["ProcessPath", "GetCommandLineArgs"]),
        ("Process", ["GetCurrentProcess"]),
        ("Assembly", ["GetEntryAssembly"]),
    ];

    // Words that can sit where a pattern's designation does and are never one.
    private static readonly HashSet<string> NotDesignations = new(StringComparer.Ordinal)
    {
        "not", "and", "or", "var", "null", "true", "false", "string", "object", "int", "long", "bool", "char", "byte",
        "double", "float", "decimal", "uint", "ulong", "short", "ushort", "sbyte", "nint", "nuint", "dynamic",
    };

    private const string DotnetHost = "\"dotnet\"";
    private const string StartInfoType = "ProcessStartInfo";

    private static readonly Regex StaticLaunch = new(@"\bProcess\s*\.\s*Start\s*\(");
    private static readonly Regex InstanceLaunch = new(@"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*Start\s*\(\s*\)");
    private static readonly Regex Identifier = new(@"^[A-Za-z_][A-Za-z0-9_]*$");
    private static readonly Regex Token = new(@"(?<![.\w])[A-Za-z_]\w*");
    private static readonly Regex NamedArgument = new(@"^([A-Za-z_][A-Za-z0-9_]*)\s*:(?!:)(.*)$", RegexOptions.Singleline);
    // A target-typed `new(...)` handed to a launch or assigned to a StartInfo can only build a start info.
    private static readonly Regex TargetTypedNew = new(@"^new\s*[({]");
    private static readonly Regex NewStartInfo = new(@"\bnew\s+(?:\w+\s*\.\s*)*ProcessStartInfo\s*\(|\bnew\s*\(");

    private sealed record Parts(List<string> Executables, List<string> Arguments);

    public static IReadOnlyList<string> Violations(string solutionRoot)
    {
        var files = SolutionTree.Files(solutionRoot);
        var directories = files
            .Where(file => file.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase))
            .Where(file => !Path.GetFileNameWithoutExtension(file).EndsWith(".Tests", StringComparison.Ordinal))
            .Select(file => Path.GetDirectoryName(file)! + Path.DirectorySeparatorChar)
            .ToList();

        // File extensions are matched without regard to case: MSBuild compiles Spawn.CS on a
        // case-insensitive file system.
        return files
            .Where(file => file.EndsWith(".cs", StringComparison.OrdinalIgnoreCase))
            .Where(file => directories.Any(directory => file.StartsWith(directory, StringComparison.Ordinal)))
            .Where(file => StartsTheTool(WithoutComments(File.ReadAllText(file))))
            .Select(file => $"{SolutionTree.Relative(solutionRoot, file)}: starts the tool's own binary")
            .Order(StringComparer.Ordinal)
            .ToList();
    }

    private static bool StartsTheTool(string text)
    {
        var hasMarker = MarkerTest(text);
        foreach (var launch in Launches(text))
        {
            var executables = launch.Executables;
            var runsTheTool = executables.Any(hasMarker);
            var runsTheHost = executables.Any(value => value.Contains(DotnetHost, StringComparison.Ordinal));
            if (runsTheTool || (runsTheHost && launch.Arguments.Any(hasMarker)))
            {
                return true;
            }
        }

        return false;
    }

    private static Func<string, bool> MarkerTest(string text)
    {
        var reached = new List<Regex>();
        foreach (var (type, members) in MarkerTypes)
        {
            var typeName = $@"(?:[\w.]+\s*\.\s*)?{type}";
            if (Regex.IsMatch(text, $@"\busing\s+static\s+{typeName}\s*;"))
            {
                reached.AddRange(members.Select(member => new Regex($@"(?<![\w.]){member}\b")));
            }

            foreach (Match alias in Regex.Matches(text, $@"\busing\s+(\w+)\s*=\s*{typeName}\s*;"))
            {
                var name = Regex.Escape(alias.Groups[1].Value);
                reached.AddRange(members.Select(member => new Regex($@"(?<![\w.]){name}\s*\.\s*{member}\b")));
            }
        }

        return value => Markers.Any(marker => value.Contains(marker, StringComparison.Ordinal))
            || reached.Any(pattern => pattern.IsMatch(value));
    }

    private static IEnumerable<Parts> Launches(string text)
    {
        foreach (Match launch in StaticLaunch.Matches(text))
        {
            var (target, others) = Bind(Arguments(text, launch.Index + launch.Length));
            if (target is null)
            {
                continue;
            }

            var resolved = Resolve(target, text, launch.Index);
            var parts = new Parts([], []);
            if (resolved.Contains(StartInfoType, StringComparison.Ordinal) || TargetTypedNew.IsMatch(resolved))
            {
                AddStartInfo(parts, resolved, text, launch.Index);
            }
            else
            {
                parts.Executables.Add(resolved);
                parts.Arguments.AddRange(others.Select(arg => Resolve(arg, text, launch.Index)));
            }

            var variable = Unwrap(target);
            if (Identifier.IsMatch(variable))
            {
                AddMembers(parts, Regex.Escape(variable), text, launch.Index);
            }

            yield return parts;
        }

        foreach (Match launch in InstanceLaunch.Matches(text))
        {
            var receiver = launch.Groups[1].Value;
            if (receiver == "Process")
            {
                continue;
            }

            var escaped = Regex.Escape(receiver);
            var parts = new Parts([], []);
            var resolvedReceiver = Resolve(receiver, text, launch.Index);
            AddStartInfo(parts, resolvedReceiver, text, launch.Index);
            foreach (var initialized in Values(resolvedReceiver, @"\bStartInfo\s*=(?![=>])", ",;}"))
            {
                AddStartInfo(parts, Resolve(initialized, text, launch.Index), text, launch.Index);
            }

            var assigned = LastAssignmentValue(text, $@"\b{escaped}\s*\.\s*StartInfo", launch.Index);
            if (assigned is not null)
            {
                AddStartInfo(parts, Resolve(assigned, text, launch.Index), text, launch.Index);
            }

            AddMembers(parts, $@"{escaped}\s*\.\s*StartInfo", text, launch.Index);
            yield return parts;
        }
    }

    // Values found in fragment are resolved against the whole text at the launch, so a
    // variable holding the own path reads as that path.
    private static void AddStartInfo(Parts parts, string fragment, string text, int launchIndex)
    {
        foreach (Match call in NewStartInfo.Matches(fragment))
        {
            var (target, others) = Bind(Arguments(fragment, call.Index + call.Length));
            if (target is not null)
            {
                parts.Executables.Add(Resolve(target, text, launchIndex));
                parts.Arguments.AddRange(others.Select(arg => Resolve(arg, text, launchIndex)));
            }
        }

        parts.Executables.AddRange(Resolved(Values(fragment, @"\bFileName\s*=(?![=>])", ",;}"), text, launchIndex));
        parts.Arguments.AddRange(Resolved(Values(fragment, @"\bArguments\s*=(?![=>])", ",;}"), text, launchIndex));
    }

    private static void AddMembers(Parts parts, string receiverPattern, string text, int launchIndex)
    {
        var before = text[..launchIndex];
        parts.Executables.AddRange(
            Resolved(Values(before, $@"\b{receiverPattern}\s*\.\s*FileName\s*=(?![=>])", ",;}"), text, launchIndex));
        parts.Arguments.AddRange(
            Resolved(Values(before, $@"\b{receiverPattern}\s*\.\s*Arguments\s*=(?![=>])", ",;}"), text, launchIndex));
        foreach (Match add in Regex.Matches(before, $@"\b{receiverPattern}\s*\.\s*ArgumentList\s*\.\s*Add\s*\("))
        {
            parts.Arguments.AddRange(Resolved(Arguments(before, add.Index + add.Length), text, launchIndex));
        }
    }

    private static IEnumerable<string> Resolved(IEnumerable<string> values, string text, int launchIndex) =>
        values.Select(value => Resolve(value, text, launchIndex)).ToList();

    // Binds the arguments of a launch or of a ProcessStartInfo constructor: the executable is the
    // first positional argument or the one named for the file name or the start info; every other
    // argument, its name dropped, is returned as an argument of the launch.
    private static (string? Target, List<string> Others) Bind(List<string> args)
    {
        var bound = args.Select(Named).ToList();
        var index = bound.FindIndex(arg => arg.Name is null or "fileName" or "startInfo");
        if (index < 0)
        {
            return (null, []);
        }

        var others = bound.Where((_, position) => position != index).Select(arg => arg.Value).ToList();
        return (bound[index].Value, others);
    }

    private static (string? Name, string Value) Named(string argument)
    {
        var match = NamedArgument.Match(argument);
        return match.Success ? (match.Groups[1].Value, match.Groups[2].Value.Trim()) : (null, argument);
    }

    private static string WithoutComments(string text)
    {
        var result = new StringBuilder(text.Length);
        var index = 0;
        while (index < text.Length)
        {
            var character = text[index];
            var next = index + 1 < text.Length ? text[index + 1] : '\0';
            if (character == '/' && next == '/')
            {
                while (index < text.Length && text[index] != '\n')
                {
                    index++;
                }

                continue;
            }

            if (character == '/' && next == '*')
            {
                var end = text.IndexOf("*/", index + 2, StringComparison.Ordinal);
                index = end < 0 ? text.Length : end + 2;
                result.Append(' ');
                continue;
            }

            var literalEnd = character switch
            {
                '"' => StringEnd(text, index),
                '\'' => CharEnd(text, index),
                _ => index,
            };
            if (literalEnd > index)
            {
                result.Append(text, index, literalEnd - index);
                index = literalEnd;
                continue;
            }

            result.Append(character);
            index++;
        }

        return result.ToString();
    }

    private static int StringEnd(string text, int start)
    {
        var quotes = 0;
        while (start + quotes < text.Length && text[start + quotes] == '"')
        {
            quotes++;
        }

        if (quotes >= 3)
        {
            var closing = text.IndexOf(new string('"', quotes), start + quotes, StringComparison.Ordinal);
            return closing < 0 ? text.Length : closing + quotes;
        }

        var verbatim = false;
        for (var back = start - 1; back >= 0 && text[back] is '@' or '$'; back--)
        {
            verbatim |= text[back] == '@';
        }

        var position = start + 1;
        while (position < text.Length)
        {
            if (text[position] == '\\' && !verbatim)
            {
                position += 2;
            }
            else if (text[position] == '"' && verbatim && position + 1 < text.Length && text[position + 1] == '"')
            {
                position += 2;
            }
            else if (text[position] == '"')
            {
                return position + 1;
            }
            else
            {
                position++;
            }
        }

        return text.Length;
    }

    private static int CharEnd(string text, int start)
    {
        var position = start + 1;
        if (position < text.Length && text[position] == '\\')
        {
            position++;
        }

        position++;
        while (position < text.Length && position - start <= 10 && text[position] != '\'')
        {
            position++;
        }

        return position < text.Length && text[position] == '\'' ? position + 1 : start;
    }

    // Follows a chain of bindings back from the launch: the expression itself first, then, joined
    // by spaces, what every variable inside it was bound to. Each step reads only text before the
    // binding it came from and a binding is followed once, so the walk ends even when a variable
    // is bound from itself and stays linear when bindings share their variables.
    private static string Resolve(string expression, string text, int launchIndex)
    {
        var collected = new List<string>();
        Follow(expression, text, launchIndex, new HashSet<int>(), collected);
        return string.Join(' ', collected);
    }

    private static void Follow(string expression, string text, int before, HashSet<int> seen, List<string> collected)
    {
        var current = Unwrap(expression);
        while (Identifier.IsMatch(current) && Binding(text, current, before) is { } binding && seen.Add(binding.Index))
        {
            current = Unwrap(binding.Value);
            before = binding.Index;
        }

        collected.Add(current);
        if (Identifier.IsMatch(current))
        {
            return;
        }

        foreach (var name in Names(current).Distinct())
        {
            if (Binding(text, name, before) is not null)
            {
                Follow(name, text, before, seen, collected);
            }
        }
    }

    // The identifiers an expression reads: those outside string literals and, in an interpolated
    // string, those inside its holes. A member name after a dot is not a variable.
    private static IEnumerable<string> Names(string expression)
    {
        var code = new StringBuilder();
        var index = 0;
        while (index < expression.Length)
        {
            if (expression[index] != '"')
            {
                code.Append(expression[index]);
                index++;
                continue;
            }

            var end = StringEnd(expression, index);
            var dollars = Dollars(expression, index);
            if (dollars > 0)
            {
                code.Append(' ').Append(Holes(expression[index..end], dollars));
            }

            code.Append(' ');
            index = end;
        }

        return Token.Matches(code.ToString()).Select(match => match.Value);
    }

    // How many `$` prefix the string that opens at the quote: none for a plain string.
    private static int Dollars(string text, int quote)
    {
        var dollars = 0;
        for (var back = quote - 1; back >= 0 && text[back] is '@' or '$'; back--)
        {
            if (text[back] == '$')
            {
                dollars++;
            }
        }

        return dollars;
    }

    // In a raw string a hole opens at a run of at least as many braces as there are `$`, and any
    // braces before its last `$`-count of them are text; elsewhere `{{` is an escaped brace.
    private static string Holes(string literal, int dollars)
    {
        var raw = literal.StartsWith("\"\"\"", StringComparison.Ordinal);
        var holes = new StringBuilder();
        for (var index = 0; index < literal.Length; index++)
        {
            if (literal[index] != '{')
            {
                continue;
            }

            if (raw)
            {
                var run = 1;
                while (index + run < literal.Length && literal[index + run] == '{')
                {
                    run++;
                }

                if (run < dollars)
                {
                    index += run - 1;
                    continue;
                }

                var inner = index + run;
                var close = Cut(literal, inner, string.Empty);
                holes.Append(' ').Append(literal, inner, close - inner);
                index = close;
                continue;
            }

            if (index + 1 < literal.Length && literal[index + 1] == '{')
            {
                index++;
                continue;
            }

            var end = Cut(literal, index + 1, string.Empty);
            holes.Append(' ').Append(literal, index + 1, end - index - 1);
            index = end;
        }

        return holes.ToString();
    }

    private sealed record Bound(string Value, int Index, bool Scoped);

    // What a name was last bound to before a point. A member read before it is declared (a field
    // below the method, an expression-bodied member) has no earlier binding, so the first one
    // after the point stands; a local binding is read only from before.
    private static (string Value, int Index)? Binding(string text, string name, int before)
    {
        var all = Bindings(text, name);
        var chosen = all.Where(bound => bound.Index < before).MaxBy(bound => bound.Index)
            ?? all.Where(bound => !bound.Scoped).MinBy(bound => bound.Index);
        return chosen is null ? null : (chosen.Value, chosen.Index);
    }

    // Every way the name is bound: an assignment, a field or property initializer, an
    // expression-bodied member (`name => value`, `name() => value`), a pattern that declares it
    // (`value is { } name`, `value is not string name`), a deconstruction and a foreach variable.
    private static List<Bound> Bindings(string text, string name)
    {
        var escaped = Regex.Escape(name);
        var bound = new List<Bound>();
        foreach (Match match in Regex.Matches(text, $@"\b{escaped}(?:\s*\{{\s*get\s*;[^{{}}]*\}})?\s*=(?![=>])"))
        {
            bound.Add(new Bound(Value(text, match.Index + match.Length, ";"), match.Index, false));
        }

        foreach (Match match in Regex.Matches(text, $@"\b{escaped}\s*(?:\([^()]*\))?\s*(?:\{{\s*get\s*)?=>"))
        {
            bound.Add(new Bound(Value(text, match.Index + match.Length, ";"), match.Index, false));
        }

        foreach (Match match in Regex.Matches(text, @"\bis\b"))
        {
            if (Designates(text, match.Index + match.Length, name))
            {
                bound.Add(new Bound(Subject(text, match.Index), match.Index, true));
            }
        }

        foreach (Match match in Regex.Matches(text, @"\(([^()]*)\)\s*=(?![=>])"))
        {
            var position = match.Groups[1].Value.Split(',').ToList()
                .FindIndex(element => element.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).LastOrDefault() == name);
            if (position >= 0)
            {
                var value = Value(text, match.Index + match.Length, ";");
                var parts = value.StartsWith('(') ? Arguments(value, 1) : [];
                var count = match.Groups[1].Value.Split(',').Length;
                bound.Add(new Bound(parts.Count == count ? parts[position] : value, match.Index, true));
            }
        }

        foreach (Match match in Regex.Matches(text, $@"\bforeach\s*\(\s*(?:[\w.<>?\[\],]+\s+)?{escaped}\s+in\b"))
        {
            bound.Add(new Bound(Value(text, match.Index + match.Length, string.Empty), match.Index, true));
        }

        return bound;
    }

    // Whether the pattern that starts at a point declares the name: the name is an identifier at
    // the pattern's own level (inside braces it names a part of the value), after a type, `not`,
    // `var` or a property pattern. The pattern ends at what cannot continue it.
    private static bool Designates(string text, int start, string name)
    {
        if (NotDesignations.Contains(name))
        {
            return false;
        }

        var depth = 0;
        var level = new StringBuilder();
        for (var index = start; index < text.Length; index++)
        {
            var character = text[index];
            var next = index + 1 < text.Length ? text[index + 1] : '\0';
            if (character is '(' or '[' or '{')
            {
                level.Append(depth == 0 ? "{}" : string.Empty);
                depth++;
            }
            else if (character is ')' or ']' or '}')
            {
                if (depth == 0)
                {
                    break;
                }

                depth--;
            }
            else if (depth > 0)
            {
                continue;
            }
            else if (character is ';' or ',' or ':' or '=' || (character == '&' && next == '&') || (character == '|' && next == '|')
                || (character == '?' && char.IsWhiteSpace(text[index - 1])))
            {
                break;
            }
            else
            {
                level.Append(character);
            }
        }

        var match = Regex.Match(level.ToString(), $@"(?<![\w.]){Regex.Escape(name)}\b(?![.(])");
        return match.Success && level.ToString(0, match.Index).Trim().Length > 0;
    }

    // The expression a pattern tests: the text before `is`, back to the nearest separator that is
    // not inside brackets.
    private static string Subject(string text, int isIndex)
    {
        var depth = 0;
        var start = isIndex;
        while (start > 0)
        {
            var character = text[start - 1];
            if (character is ')' or ']')
            {
                depth++;
            }
            else if (character is '(' or '[')
            {
                if (depth == 0)
                {
                    break;
                }

                depth--;
            }
            else if (depth == 0 && IsSeparator(text, start - 1))
            {
                break;
            }

            start--;
        }

        return text[start..isIndex].Trim();
    }

    private static bool IsSeparator(string text, int index) =>
        text[index] is ';' or ',' or '{' or '}' or '=' or ':' or '&' or '|'
        || (text[index] == '?' && !(index + 1 < text.Length && text[index + 1] is '.' or '['));

    // Drops what leaves a value's identity alone: surrounding whitespace, a null-forgiving
    // operator and enclosing parentheses.
    private static string Unwrap(string expression)
    {
        var current = expression.Trim();
        while (true)
        {
            if (current.EndsWith('!'))
            {
                current = current[..^1].TrimEnd();
            }
            else if (current.StartsWith('(') && Cut(current, 1, string.Empty) == current.Length - 1)
            {
                current = current[1..^1].Trim();
            }
            else
            {
                return current;
            }
        }
    }

    private static string? LastAssignmentValue(string text, string targetPattern, int launchIndex) =>
        LastAssignment(text, targetPattern, launchIndex)?.Value;

    private static (string Value, int Index)? LastAssignment(string text, string targetPattern, int launchIndex)
    {
        var last = Regex.Matches(text[..launchIndex], $@"{targetPattern}\s*=(?![=>])").LastOrDefault();
        return last is null ? null : (Value(text, last.Index + last.Length, ";"), last.Index);
    }

    private static List<string> Values(string text, string pattern, string stops) =>
        Regex.Matches(text, pattern).Select(match => Value(text, match.Index + match.Length, stops)).ToList();

    private static string Value(string text, int start, string stops) =>
        text[start..Cut(text, start, stops)].Trim();

    private static List<string> Arguments(string text, int start)
    {
        var args = new List<string>();
        var position = start;
        while (position <= text.Length)
        {
            var end = Cut(text, position, ",");
            var argument = text[position..end].Trim();
            if (argument.Length > 0)
            {
                args.Add(argument);
            }

            if (end >= text.Length || text[end] != ',')
            {
                break;
            }

            position = end + 1;
        }

        return args;
    }

    private static int Cut(string text, int start, string stops)
    {
        var depth = 0;
        for (var index = start; index < text.Length; index++)
        {
            var character = text[index];
            if (character is '(' or '[' or '{')
            {
                depth++;
            }
            else if (character is ')' or ']' or '}')
            {
                if (depth == 0)
                {
                    return index;
                }

                depth--;
            }
            else if (depth == 0 && stops.Contains(character))
            {
                return index;
            }
        }

        return text.Length;
    }
}
