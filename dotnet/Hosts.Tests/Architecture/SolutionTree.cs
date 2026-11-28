namespace AgentTools.Hosts.Tests.Architecture;

public static class SolutionTree
{
    private const string SolutionFile = "AgentTools.slnx";

    public static string Root()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
        {
            if (File.Exists(Path.Combine(directory.FullName, SolutionFile)))
            {
                return directory.FullName;
            }
        }

        throw new InvalidOperationException($"no ancestor of {AppContext.BaseDirectory} holds {SolutionFile}");
    }

    public static string Guide(string root) =>
        Path.GetFullPath(Path.Combine(root, "..", "docs", "guides", "architecture.md"));

    internal static IReadOnlyList<string> Files(string root)
    {
        var files = new List<string>();
        var pending = new Stack<string>();
        pending.Push(root);
        while (pending.Count > 0)
        {
            var directory = pending.Pop();
            files.AddRange(Directory.EnumerateFiles(directory));
            foreach (var child in Directory.EnumerateDirectories(directory))
            {
                var name = Path.GetFileName(child);
                if (name is not ("bin" or "obj"))
                {
                    pending.Push(child);
                }
            }
        }

        files.Sort(StringComparer.Ordinal);
        return files;
    }

    internal static string Relative(string root, string path) =>
        Path.GetRelativePath(root, path).Replace(Path.DirectorySeparatorChar, '/');
}
