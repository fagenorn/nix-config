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
            .Where(file => file.EndsWith(".csproj", StringComparison.Ordinal))
            .Where(file => !Path.GetFileNameWithoutExtension(file).EndsWith(".Tests", StringComparison.Ordinal))
            .Select(file => Path.GetDirectoryName(file)! + Path.DirectorySeparatorChar)
            .ToList();

        return files
            .Where(file => file.EndsWith(".cs", StringComparison.Ordinal))
            .Where(file => directories.Any(directory => file.StartsWith(directory, StringComparison.Ordinal)))
            .Where(file => StartsTheTool(WithoutComments(File.ReadAllText(file))))
            .Select(file => $"{SolutionTree.Relative(solutionRoot, file)}: starts the tool's own binary")
            .Order(StringComparer.Ordinal)
            .ToList();
    }

    private static bool StartsTheTool(string text)
    {
        foreach (var launch in Launches(text))
        {
            var executables = launch.Executables;
            var runsTheTool = executables.Any(HasMarker);
            var runsTheHost = executables.Any(value => value.Contains(DotnetHost, StringComparison.Ordinal));
            if (runsTheTool || (runsTheHost && launch.Arguments.Any(HasMarker)))
            {
                return true;
            }
        }

        return false;
    }

    private static bool HasMarker(string value) =>
        Markers.Any(marker => value.Contains(marker, StringComparison.Ordinal));

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
            if (IsInterpolated(expression, index))
            {
                code.Append(' ').Append(Holes(expression[index..end]));
            }

            code.Append(' ');
            index = end;
        }

        return Token.Matches(code.ToString()).Select(match => match.Value);
    }

    private static bool IsInterpolated(string text, int quote)
    {
        for (var back = quote - 1; back >= 0 && text[back] is '@' or '$'; back--)
        {
            if (text[back] == '$')
            {
                return true;
            }
        }

        return false;
    }

    private static string Holes(string literal)
    {
        var holes = new StringBuilder();
        for (var index = 0; index < literal.Length; index++)
        {
            if (literal[index] != '{')
            {
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

    // What a name was last bound to before a point: an assignment, or a pattern that declares it
    // (`value is { } name`, `value is string name`), whose value is the matched expression.
    private static (string Value, int Index)? Binding(string text, string name, int before)
    {
        var escaped = Regex.Escape(name);
        var assigned = LastAssignment(text, $@"\b{escaped}", before);
        var pattern = Regex
            .Matches(text[..before], $@"\bis\s+(?:\{{[^{{}}]*\}}\s*|[A-Za-z_][\w.<>?\[\]]*\s+){escaped}\b")
            .LastOrDefault();
        if (pattern is null)
        {
            return assigned;
        }

        return assigned is { } found && found.Index > pattern.Index ? found : (Subject(text, pattern.Index), pattern.Index);
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
