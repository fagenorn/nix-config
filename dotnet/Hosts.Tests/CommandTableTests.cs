using AgentTools.Hosts;
using Xunit;

namespace AgentTools.Hosts.Tests;

public sealed class CommandTableTests
{
    [Fact]
    public void CommandsJsonPrintsTheTable()
    {
        var output = new StringWriter();

        var code = CommandTable.Build(output).Parse(["commands", "--json"]).Invoke();

        Assert.Equal(0, code);
        Assert.Equal("[\"commands\"]\n", output.ToString());
    }

    [Fact]
    public void CommandsPrintsOneIdPerLine()
    {
        var output = new StringWriter();

        var code = CommandTable.Build(output).Parse(["commands"]).Invoke();

        Assert.Equal(0, code);
        Assert.Equal("commands\n", output.ToString());
    }

    [Fact]
    public void AnUnknownCommandFails()
    {
        var code = CommandTable.Build(new StringWriter()).Parse(["nope"]).Invoke();

        Assert.NotEqual(0, code);
    }

    [Fact]
    public void TheTableHoldsOnlyTheListing()
    {
        Assert.Equal(new[] { "commands" }, CommandTable.Ids);
    }
}
