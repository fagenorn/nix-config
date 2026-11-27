using System.Xml.Linq;

namespace AgentTools.Hosts.Tests.Architecture;

public sealed record ProjectFile(string Name, IReadOnlyList<string> References);

public sealed record SolutionGraph(IReadOnlyList<ProjectFile> Projects, IReadOnlyList<string> Declarations)
{
    private const string SharedProps = "Directory.Build.props";
    private const string SharedPackages = "Directory.Packages.props";
    private const string Setting = "DisableTransitiveProjectReferences";

    public static SolutionGraph Read(string solutionRoot)
    {
        var projects = new List<ProjectFile>();
        var declarations = new HashSet<string>(StringComparer.Ordinal);
        var sawSharedSetting = false;

        foreach (var file in SolutionTree.Files(solutionRoot))
        {
            var rel = SolutionTree.Relative(solutionRoot, file);
            var isProject = file.EndsWith(".csproj", StringComparison.Ordinal);
            var isOther = file.EndsWith(".props", StringComparison.Ordinal)
                || file.EndsWith(".targets", StringComparison.Ordinal)
                || file.EndsWith(".user", StringComparison.Ordinal);
            if (!isProject && !isOther)
            {
                continue;
            }

            if (!isProject && rel != SharedProps && rel != SharedPackages)
            {
                declarations.Add($"{rel}: unsupported MSBuild file");
                continue;
            }

            var document = XDocument.Load(file);
            foreach (var _ in Elements(document, "Import"))
            {
                declarations.Add($"{rel}: Import is not supported");
            }

            var settings = Elements(document, Setting).ToList();
            if (settings.Any(NotTrue))
            {
                declarations.Add($"{rel}: {Setting} is not true");
            }

            var references = Elements(document, "ProjectReference")
                .Select(element => element.Attribute("Include")?.Value)
                .OfType<string>()
                .SelectMany(include => include.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                .Select(item => Path.GetFileNameWithoutExtension(item.Replace('\\', '/')))
                .ToList();

            if (isProject)
            {
                projects.Add(new ProjectFile(Path.GetFileNameWithoutExtension(file), references));
                continue;
            }

            foreach (var reference in references)
            {
                declarations.Add($"{rel}: ProjectReference to {reference} outside a project file");
            }

            sawSharedSetting |= rel == SharedProps && settings.Any(setting => !NotTrue(setting));
        }

        if (!sawSharedSetting)
        {
            declarations.Add($"{SharedProps}: {Setting} is not true");
        }

        return new SolutionGraph(projects, declarations.Order(StringComparer.Ordinal).ToList());
    }

    public IReadOnlyList<string> Violations(EdgeTable table)
    {
        var violations = new List<string>(Declarations);
        foreach (var project in Projects)
        {
            if (!table.Knows(project.Name))
            {
                violations.Add($"{project.Name}: project not in the edge table");
                continue;
            }

            violations.AddRange(
                project.References
                    .Where(reference => !table.Allows(project.Name, reference))
                    .Select(reference => $"{project.Name} -> {reference}: reference outside the edge table"));
        }

        return violations.Order(StringComparer.Ordinal).ToList();
    }

    // MSBuild matches item and property names without regard to case.
    private static IEnumerable<XElement> Elements(XDocument document, string localName) =>
        document.Descendants().Where(element => IsNamed(element, localName));

    private static bool IsNamed(XElement element, string localName) =>
        string.Equals(element.Name.LocalName, localName, StringComparison.OrdinalIgnoreCase);

    private static bool IsConditional(XElement element) =>
        element.Attribute("Condition") is not null || element.Name.LocalName is "Choose" or "When" or "Otherwise";

    // Only a property group directly under the project root is evaluated with the project;
    // one inside a target takes effect, if at all, only when the target runs.
    private static bool AssignedDuringEvaluation(XElement setting) =>
        setting.Parent is { } group && IsNamed(group, "PropertyGroup") && group.Parent == setting.Document?.Root;

    private static bool NotTrue(XElement setting) =>
        !AssignedDuringEvaluation(setting)
            || setting.AncestorsAndSelf().Any(IsConditional)
            || !string.Equals(setting.Value.Trim(), "true", StringComparison.OrdinalIgnoreCase);
}
