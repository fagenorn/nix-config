using System.Text;

namespace AgentTools.Hosts.Tests.Architecture;

public sealed class PlantedSolution : IDisposable
{
    public const string Guide = """
        | Layer | Project | References |
        |---|---|---|
        | L6 | Hosts (root) | System |
        | L0 | System | none |
        """;

    private readonly DirectoryInfo directory = Directory.CreateTempSubdirectory("planted-solution-");

    public string Root => directory.FullName;

    public void Project(string name, params string[] references)
    {
        var text = new StringBuilder("<Project Sdk=\"Microsoft.NET.Sdk\">");
        foreach (var reference in references)
        {
            text.Append($"<ItemGroup><ProjectReference Include=\"../{reference}/{reference}.csproj\" /></ItemGroup>");
        }

        text.Append("</Project>");
        Source($"{name}/{name}.csproj", text.ToString());
    }

    public void Props(string? transitiveValue)
    {
        var setting = transitiveValue is null
            ? string.Empty
            : $"<PropertyGroup><DisableTransitiveProjectReferences>{transitiveValue}</DisableTransitiveProjectReferences></PropertyGroup>";
        Source("Directory.Build.props", $"<Project>{setting}</Project>");
    }

    public void Source(string relativePath, string text)
    {
        var path = Path.Combine(Root, relativePath);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, text);
    }

    public void Dispose() => directory.Delete(recursive: true);
}
