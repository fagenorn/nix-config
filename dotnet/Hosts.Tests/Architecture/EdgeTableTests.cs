using Xunit;

namespace AgentTools.Hosts.Tests.Architecture;

public sealed class EdgeTableTests
{
    private static readonly string[] RecordProjects =
    [
        "Claims",
        "Console",
        "Delivery",
        "Guard",
        "Hosts",
        "ProjectContract",
        "Release",
        "System",
        "Verification",
    ];

    private static readonly string[] RecordEdges =
    [
        "Hosts -> Console",
        "Hosts -> Delivery",
        "Hosts -> Verification",
        "Hosts -> Release",
        "Hosts -> Guard",
        "Hosts -> Claims",
        "Hosts -> ProjectContract",
        "Hosts -> System",
        "Console -> Delivery",
        "Console -> Verification",
        "Console -> Release",
        "Console -> Claims",
        "Console -> ProjectContract",
        "Console -> System",
        "Delivery -> Verification",
        "Delivery -> Claims",
        "Delivery -> ProjectContract",
        "Delivery -> System",
        "Release -> Guard",
        "Release -> Claims",
        "Release -> ProjectContract",
        "Release -> System",
        "Verification -> Guard",
        "Verification -> Claims",
        "Verification -> ProjectContract",
        "Verification -> System",
        "Claims -> ProjectContract",
        "Claims -> System",
        "Guard -> ProjectContract",
        "Guard -> System",
        "ProjectContract -> System",
    ];

    private static EdgeTable RealGuide() =>
        EdgeTable.FromGuide(File.ReadAllText(SolutionTree.Guide(SolutionTree.Root())));

    [Fact]
    public void TheGuideHoldsExactlyTheRecordsEdges()
    {
        var table = RealGuide();

        var projects = table.References.Keys.Order(StringComparer.Ordinal).ToArray();
        var expectedEdges = RecordEdges.Order(StringComparer.Ordinal).ToArray();

        Assert.Equal(RecordProjects, projects);
        Assert.Equal(expectedEdges, table.Edges);
        Assert.Equal(31, table.Edges.Count);
    }

    [Theory]
    [InlineData("Release", "Verification")]
    [InlineData("Release", "Delivery")]
    [InlineData("Claims", "Guard")]
    [InlineData("Delivery", "Guard")]
    [InlineData("Console", "Guard")]
    public void TheGuideAllowsNoForbiddenPair(string first, string second)
    {
        var table = RealGuide();

        Assert.False(table.Allows(first, second));
        Assert.False(table.Allows(second, first));
    }

    [Fact]
    public void AProjectCellIsReadUpToItsParenthesis()
    {
        var table = EdgeTable.FromGuide(PlantedSolution.Guide);

        Assert.True(table.Knows("Hosts"));
        Assert.True(table.Allows("Hosts", "System"));
        Assert.False(table.Knows("Hosts (root)"));
    }

    [Fact]
    public void NoneIsTheEmptySet()
    {
        var table = EdgeTable.FromGuide(PlantedSolution.Guide);

        Assert.Empty(table.References["System"]);
    }

    [Fact]
    public void AGuideWithoutTheTableThrows()
    {
        var thrown = Assert.Throws<InvalidOperationException>(() => EdgeTable.FromGuide("# Title\n"));

        Assert.Equal("the guide holds no edge table", thrown.Message);
    }
}
