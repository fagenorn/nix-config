using Xunit;

namespace AgentTools.Hosts.Tests.Architecture;

public sealed class SelfStartTests
{
    private const string OwnBinary = "Hosts/Spawn.cs: starts the tool's own binary";

    private static IReadOnlyList<string> ViolationsOfHostsSource(string source)
    {
        using var planted = new PlantedSolution();
        planted.Project("Hosts");
        planted.Source("Hosts/Spawn.cs", source);
        return SelfStart.Violations(planted.Root);
    }

    [Theory]
    [InlineData("Process.Start(Environment.ProcessPath!);")]
    [InlineData("Process.Start(Environment.GetCommandLineArgs()[0]);")]
    [InlineData("Process.Start(Process.GetCurrentProcess().MainModule!.FileName);")]
    [InlineData("Process.Start(Assembly.GetEntryAssembly()!.Location);")]
    [InlineData("Process.Start(\"agent-tools\", \"commands\");")]
    [InlineData("Process.Start (Environment.ProcessPath!);")]
    [InlineData("var info = new ProcessStartInfo(Environment.ProcessPath!); Process.Start(info);")]
    [InlineData("var info = new ProcessStartInfo { FileName = Environment.ProcessPath! }; Process.Start(info);")]
    [InlineData("using var p = new Process { StartInfo = { FileName = Environment.ProcessPath! } }; p.Start();")]
    [InlineData("Process.Start(\"dotnet\", Assembly.GetEntryAssembly()!.Location);")]
    [InlineData("var p = new Process(); p.StartInfo = new ProcessStartInfo(Environment.ProcessPath!); p.Start();")]
    [InlineData("var info = new ProcessStartInfo(); info.FileName = Environment.ProcessPath!; Process.Start(info);")]
    [InlineData(
        "var info = new ProcessStartInfo { FileName = \"dotnet\", Arguments = Assembly.GetEntryAssembly()!.Location };"
            + " Process.Start(info);")]
    [InlineData(
        "var info = new ProcessStartInfo(\"dotnet\"); info.ArgumentList.Add(Assembly.GetEntryAssembly()!.Location);"
            + " Process.Start(info);")]
    public void StartingTheToolsOwnBinaryIsAViolation(string source)
    {
        Assert.Equal(new[] { OwnBinary }, ViolationsOfHostsSource(source));
    }

    [Fact]
    public void StartingAnotherProgramIsNoViolation()
    {
        Assert.Empty(ViolationsOfHostsSource("Process.Start(\"git\", \"status\");"));
    }

    [Fact]
    public void AnArgumentOfAnotherProgramIsNoViolation()
    {
        Assert.Empty(ViolationsOfHostsSource("Process.Start(\"git\", \"agent-tools\");"));
    }

    [Fact]
    public void RecordingTheOwnPathBesideAnotherStartIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath;\nProcess.Start(\"git\", \"status\");";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void AStartInfoThatStartsNothingIsNoViolation()
    {
        Assert.Empty(ViolationsOfHostsSource("var info = new ProcessStartInfo(Environment.ProcessPath!);"));
    }

    [Fact]
    public void AStartInfoForAnotherProgramIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath; var info = new ProcessStartInfo(\"git\"); Process.Start(info);";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void AnUnstartedSelfInfoBesideAnotherStartIsNoViolation()
    {
        var source = "var mine = new ProcessStartInfo { FileName = Environment.ProcessPath! }; "
            + "using var q = new Process { StartInfo = { FileName = \"git\" } }; q.Start();";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void ATestProjectIsNotScanned()
    {
        using var planted = new PlantedSolution();
        planted.Project("Hosts.Tests");
        planted.Source("Hosts.Tests/Spawn.cs", "Process.Start(Environment.ProcessPath!);");

        Assert.Empty(SelfStart.Violations(planted.Root));
    }

    [Fact]
    public void NoProductionSourceStartsTheTool()
    {
        Assert.Empty(SelfStart.Violations(SolutionTree.Root()));
    }
}
