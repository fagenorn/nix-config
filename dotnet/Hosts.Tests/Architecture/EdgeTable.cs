namespace AgentTools.Hosts.Tests.Architecture;

public sealed record EdgeTable(IReadOnlyDictionary<string, IReadOnlySet<string>> References)
{
    private const string TestsSuffix = ".Tests";

    public IReadOnlyList<string> Edges =>
        References
            .SelectMany(row => row.Value.Select(to => $"{row.Key} -> {to}"))
            .Order(StringComparer.Ordinal)
            .ToList();

    public static EdgeTable FromGuide(string markdown)
    {
        var lines = markdown.Split('\n').Select(line => line.Trim()).ToList();
        var header = lines.FindIndex(line => Cells(line) is ["Layer", "Project", "References"]);
        if (header < 0)
        {
            throw new InvalidOperationException("the guide holds no edge table");
        }

        var rows = new Dictionary<string, IReadOnlySet<string>>(StringComparer.Ordinal);
        foreach (var line in lines.Skip(header + 2).TakeWhile(line => line.StartsWith('|')))
        {
            var cells = Cells(line);
            var cell = cells[1];
            var end = cell.IndexOfAny([' ', '(']);
            var project = end < 0 ? cell : cell[..end];
            rows[project] = cells[2]
                .Split(',')
                .Select(reference => reference.Trim())
                .Where(reference => reference.Length > 0 && reference != "none")
                .ToHashSet(StringComparer.Ordinal);
        }

        return new EdgeTable(rows);
    }

    public bool Knows(string project) => References.ContainsKey(project) || Owner(project) is not null;

    public bool Allows(string from, string to)
    {
        if (References.TryGetValue(from, out var row))
        {
            return row.Contains(to);
        }

        var owner = Owner(from);
        return owner is not null && (to == owner || References[owner].Contains(to));
    }

    private string? Owner(string project) =>
        project.EndsWith(TestsSuffix, StringComparison.Ordinal) && References.ContainsKey(project[..^TestsSuffix.Length])
            ? project[..^TestsSuffix.Length]
            : null;

    private static string[] Cells(string line) =>
        line.Trim('|').Split('|').Select(cell => cell.Trim()).ToArray();
}
