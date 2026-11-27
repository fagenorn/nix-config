using Xunit;

namespace AgentTools.Hosts.Tests.Architecture;

public sealed class ReferenceGraphTests
{
    private const string TransitiveTrue =
        "<PropertyGroup><DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup>";

    private static IReadOnlyList<string> Violations(PlantedSolution planted)
    {
        var table = EdgeTable.FromGuide(PlantedSolution.Guide);
        return SolutionGraph.Read(planted.Root).Violations(table);
    }

    [Fact]
    public void AnUpwardReferenceIsOutsideTheEdgeTable()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("System", "Hosts");
        planted.Project("Hosts");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System -> Hosts: reference outside the edge table" }, violations);
    }

    [Fact]
    public void AnAllowedReferenceIsNoViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("Hosts", "System");
        planted.Project("System");

        Assert.Empty(Violations(planted));
    }

    [Fact]
    public void AReferenceToATestProjectIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("Hosts", "Hosts.Tests");
        planted.Project("Hosts.Tests");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Hosts -> Hosts.Tests: reference outside the edge table" }, violations);
    }

    [Fact]
    public void ATestProjectMayReferenceItsProjectAndItsRow()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("Hosts.Tests", "Hosts", "System");
        planted.Project("Hosts", "System");
        planted.Project("System");

        Assert.Empty(Violations(planted));
    }

    [Fact]
    public void ATestProjectMayNotReferenceAboveItsProject()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("System.Tests", "Hosts");
        planted.Project("Hosts");
        planted.Project("System");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System.Tests -> Hosts: reference outside the edge table" }, violations);
    }

    [Fact]
    public void AProjectOutsideTheTableIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("Widget");

        Assert.Equal(new[] { "Widget: project not in the edge table" }, Violations(planted));
    }

    [Fact]
    public void ATestProjectOfAnUnknownProjectIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("Widget.Tests");

        Assert.Equal(new[] { "Widget.Tests: project not in the edge table" }, Violations(planted));
    }

    [Fact]
    public void ATransitiveOverrideIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Source(
            "System/System.csproj",
            "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup>"
                + "<DisableTransitiveProjectReferences>false</DisableTransitiveProjectReferences>"
                + "</PropertyGroup></Project>");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System/System.csproj: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void ALowercaseReferenceElementIsRead()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Source(
            "System/System.csproj",
            "<Project Sdk=\"Microsoft.NET.Sdk\"><ItemGroup>"
                + "<projectreference Include=\"../Hosts/Hosts.csproj\" /></ItemGroup></Project>");
        planted.Project("Hosts");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System -> Hosts: reference outside the edge table" }, violations);
    }

    [Fact]
    public void ALowercaseTransitiveOverrideIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Source(
            "System/System.csproj",
            "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup>"
                + "<disabletransitiveprojectreferences>false</disabletransitiveprojectreferences>"
                + "</PropertyGroup></Project>");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System/System.csproj: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void ASharedSettingInsideATargetIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Source(
            "Directory.Build.props",
            "<Project><Target Name=\"Never\">" + TransitiveTrue + "</Target></Project>");
        planted.Project("System");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.props: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void ABackslashReferenceIsRead()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Source(
            "System/System.csproj",
            "<Project Sdk=\"Microsoft.NET.Sdk\"><ItemGroup>"
                + "<ProjectReference Include=\"..\\Hosts\\Hosts.csproj\" /></ItemGroup></Project>");
        planted.Project("Hosts");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System -> Hosts: reference outside the edge table" }, violations);
    }

    [Fact]
    public void ASharedPropsWithoutTheSettingIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props(null);
        planted.Project("System");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.props: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void AMissingSharedPropsIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Project("System");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.props: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void AConditionalSharedSettingIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Source(
            "Directory.Build.props",
            "<Project><PropertyGroup Condition=\"'$(Configuration)' == 'Release'\">"
                + "<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>"
                + "</PropertyGroup></Project>");
        planted.Project("System");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.props: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void ASemicolonListedReferenceIsReadItemByItem()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("System");
        planted.Project("Hosts.Tests");
        planted.Source(
            "Hosts/Hosts.csproj",
            "<Project Sdk=\"Microsoft.NET.Sdk\"><ItemGroup>"
                + "<ProjectReference Include=\"../Hosts.Tests/Hosts.Tests.csproj;../System/System.csproj\" />"
                + "</ItemGroup></Project>");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Hosts -> Hosts.Tests: reference outside the edge table" }, violations);
    }

    [Fact]
    public void ASharedSettingInAChooseBranchIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Source(
            "Directory.Build.props",
            "<Project><Choose><When Condition=\"'$(Configuration)' == 'Release'\"><PropertyGroup /></When>"
                + "<Otherwise>" + TransitiveTrue + "</Otherwise></Choose></Project>");
        planted.Project("System");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.props: DisableTransitiveProjectReferences is not true" }, violations);
    }

    [Fact]
    public void AProjectUserFileIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("System");
        planted.Project("Hosts");
        planted.Source(
            "System/System.csproj.user",
            "<Project><PropertyGroup><DisableTransitiveProjectReferences>false</DisableTransitiveProjectReferences>"
                + "</PropertyGroup><ItemGroup><ProjectReference Include=\"../Hosts/Hosts.csproj\" /></ItemGroup></Project>");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System/System.csproj.user: unsupported MSBuild file" }, violations);
    }

    [Fact]
    public void ASharedPropsReferenceIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Source(
            "Directory.Build.props",
            "<Project>" + TransitiveTrue
                + "<ItemGroup Condition=\"'$(MSBuildProjectName)' == 'System'\">"
                + "<ProjectReference Include=\"$(MSBuildThisFileDirectory)Hosts/Hosts.csproj\" />"
                + "</ItemGroup></Project>");
        planted.Project("System");
        planted.Project("Hosts");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.props: ProjectReference to Hosts outside a project file" }, violations);
    }

    [Fact]
    public void AnotherMSBuildFileIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Project("System");
        planted.Source(
            "Directory.Build.targets",
            "<Project><PropertyGroup>"
                + "<DisableTransitiveProjectReferences>false</DisableTransitiveProjectReferences>"
                + "</PropertyGroup></Project>");

        var violations = Violations(planted);

        Assert.Equal(new[] { "Directory.Build.targets: unsupported MSBuild file" }, violations);
    }

    [Fact]
    public void AnImportIsAViolation()
    {
        using var planted = new PlantedSolution();
        planted.Props("true");
        planted.Source(
            "System/System.csproj",
            "<Project Sdk=\"Microsoft.NET.Sdk\"><Import Project=\"../../shared.props\" /></Project>");

        var violations = Violations(planted);

        Assert.Equal(new[] { "System/System.csproj: Import is not supported" }, violations);
    }

    [Fact]
    public void TheSolutionHoldsTheEdgeTable()
    {
        var root = SolutionTree.Root();
        var graph = SolutionGraph.Read(root);
        var table = EdgeTable.FromGuide(File.ReadAllText(SolutionTree.Guide(root)));

        var names = graph.Projects.Select(project => project.Name).ToList();

        Assert.Contains("Hosts", names);
        Assert.Contains("System", names);
        Assert.Contains("Hosts.Tests", names);
        Assert.Empty(graph.Violations(table));
    }
}
