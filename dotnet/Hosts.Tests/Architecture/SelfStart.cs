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
    private static readonly Regex NewStartInfo = new(@"\bnew\s+(?:\w+\s*\.\s*)*ProcessStartInfo\s*\(");

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
            .Where(file => StartsTheTool(File.ReadAllText(file)))
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
            var args = Arguments(text, launch.Index + launch.Length);
            if (args.Count == 0)
            {
                continue;
            }

            var resolved = Resolve(args[0], text, launch.Index);
            var parts = new Parts([], []);
            if (resolved.Contains(StartInfoType, StringComparison.Ordinal))
            {
                AddStartInfo(parts, resolved);
            }
            else
            {
                parts.Executables.Add(resolved);
                parts.Arguments.AddRange(args.Skip(1).Select(arg => Resolve(arg, text, launch.Index)));
            }

            if (Identifier.IsMatch(args[0]))
            {
                AddMembers(parts, Regex.Escape(args[0]), text[..launch.Index]);
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

            var before = text[..launch.Index];
            var escaped = Regex.Escape(receiver);
            var parts = new Parts([], []);
            var resolvedReceiver = Resolve(receiver, text, launch.Index);
            AddStartInfo(parts, resolvedReceiver);
            foreach (var initialized in Values(resolvedReceiver, @"\bStartInfo\s*=(?![=>])", ",;}"))
            {
                AddStartInfo(parts, Resolve(initialized, text, launch.Index));
            }

            var assigned = LastAssignmentValue(text, $@"\b{escaped}\s*\.\s*StartInfo", launch.Index);
            if (assigned is not null)
            {
                AddStartInfo(parts, Resolve(assigned, text, launch.Index));
            }

            AddMembers(parts, $@"{escaped}\s*\.\s*StartInfo", before);
            yield return parts;
        }
    }

    private static void AddStartInfo(Parts parts, string text)
    {
        foreach (Match call in NewStartInfo.Matches(text))
        {
            var args = Arguments(text, call.Index + call.Length);
            if (args.Count > 0)
            {
                parts.Executables.Add(args[0]);
                parts.Arguments.AddRange(args.Skip(1));
            }
        }

        parts.Executables.AddRange(Values(text, @"\bFileName\s*=(?![=>])", ",;}"));
        parts.Arguments.AddRange(Values(text, @"\bArguments\s*=(?![=>])", ",;}"));
    }

    private static void AddMembers(Parts parts, string receiverPattern, string before)
    {
        parts.Executables.AddRange(Values(before, $@"\b{receiverPattern}\s*\.\s*FileName\s*=(?![=>])", ",;}"));
        parts.Arguments.AddRange(Values(before, $@"\b{receiverPattern}\s*\.\s*Arguments\s*=(?![=>])", ",;}"));
        foreach (Match add in Regex.Matches(before, $@"\b{receiverPattern}\s*\.\s*ArgumentList\s*\.\s*Add\s*\("))
        {
            parts.Arguments.AddRange(Arguments(before, add.Index + add.Length));
        }
    }

    private static string Resolve(string expression, string text, int launchIndex)
    {
        var trimmed = expression.Trim();
        if (!Identifier.IsMatch(trimmed))
        {
            return trimmed;
        }

        return LastAssignmentValue(text, $@"\b{Regex.Escape(trimmed)}", launchIndex) ?? trimmed;
    }

    private static string? LastAssignmentValue(string text, string targetPattern, int launchIndex)
    {
        var last = Regex.Matches(text[..launchIndex], $@"{targetPattern}\s*=(?![=>])").LastOrDefault();
        return last is null ? null : Value(text, last.Index + last.Length, ";");
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
