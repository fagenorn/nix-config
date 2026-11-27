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
    [InlineData("var info = new ProcessStartInfo(Environment.ProcessPath!); using var p = new Process { StartInfo = info }; p.Start();")]
    [InlineData(
        "var info = new ProcessStartInfo { FileName = Environment.ProcessPath! };"
            + " using var p = new Process { StartInfo = info }; p.Start();")]
    [InlineData("var exe = Environment.ProcessPath!; Process.Start(new ProcessStartInfo(exe));")]
    [InlineData(
        "var exe = Environment.ProcessPath!; var info = new ProcessStartInfo { FileName = exe }; Process.Start(info);")]
    [InlineData(
        "var exe = Environment.ProcessPath!; var info = new ProcessStartInfo(); info.FileName = exe; Process.Start(info);")]
    [InlineData("Process.Start(arguments: \"commands\", fileName: \"agent-tools\");")]
    [InlineData("Process.Start(new ProcessStartInfo(arguments: \"commands\", fileName: \"agent-tools\"));")]
    [InlineData("Process.Start(startInfo: new ProcessStartInfo(Environment.ProcessPath!));")]
    [InlineData("var url = \"http://host\"; Process.Start(Environment.ProcessPath!);")]
    [InlineData("var exe = Environment.ProcessPath; Process.Start(exe!);")]
    [InlineData("var exe = Environment.ProcessPath; Process.Start((exe));")]
    [InlineData("var exe = Environment.ProcessPath; Process.Start((exe)!);")]
    [InlineData("var self = Environment.ProcessPath!; var exe = self; Process.Start(exe);")]
    [InlineData("var self = Environment.ProcessPath!; var mid = self; var exe = mid!; Process.Start(exe);")]
    [InlineData("var exe = Environment.ProcessPath!; ProcessStartInfo info = new(exe); Process.Start(info);")]
    [InlineData("var exe = Environment.ProcessPath!; ProcessStartInfo info = new() { FileName = exe }; Process.Start(info);")]
    [InlineData("var exe = Environment.ProcessPath!; ProcessStartInfo info = new(exe); Process.Start(info!);")]
    [InlineData("var exe = Environment.ProcessPath!; Process.Start(new ProcessStartInfo(exe!));")]
    [InlineData("var exe = Environment.ProcessPath!; using var p = new Process { StartInfo = new(exe) }; p.Start();")]
    [InlineData("var exe = Environment.ProcessPath!; var p = new Process(); p.StartInfo = new() { FileName = exe }; p.Start();")]
    [InlineData("if (Environment.ProcessPath is { } exe) { Process.Start(exe); }")]
    [InlineData("if (Environment.ProcessPath is string exe) { Process.Start(exe); }")]
    [InlineData("if (Environment.ProcessPath is var exe && exe is not null) { Process.Start(exe); }")]
    [InlineData("if (Environment.ProcessPath is { Length: > 0 } exe) { Process.Start(new ProcessStartInfo(exe)); }")]
    [InlineData("var self = Assembly.GetEntryAssembly()!.Location; Process.Start(\"dotnet\", $\"{self} commands\");")]
    [InlineData("var self = Assembly.GetEntryAssembly()!.Location; Process.Start(\"dotnet\", self + \" commands\");")]
    [InlineData("var self = Environment.ProcessPath!; Process.Start(self + \" commands\");")]
    [InlineData("var self = Environment.ProcessPath!; Process.Start(Path.Combine(\"bin\", self));")]
    [InlineData("var self = Assembly.GetEntryAssembly()!.Location; var line = $\"{self} commands\"; Process.Start(\"dotnet\", line);")]
    [InlineData("var self = Environment.ProcessPath!; var info = new ProcessStartInfo { FileName = $\"{self}\" }; Process.Start(info);")]
    [InlineData("if (Environment.ProcessPath is not { } exe) { return; } Process.Start(exe);")]
    [InlineData("if (Environment.ProcessPath is not string exe) { return; } Process.Start(exe);")]
    [InlineData("if (Environment.ProcessPath is string { Length: > 0 } exe) { Process.Start(exe); }")]
    [InlineData("if (Environment.ProcessPath is { Length: > 0 } and var exe) { Process.Start(exe); }")]
    [InlineData("class C { static string Exe => Environment.ProcessPath!; void Run() { Process.Start(Exe); } }")]
    [InlineData("class C { static string Self() => Environment.ProcessPath!; void Run() { Process.Start(Self()); } }")]
    [InlineData("class C { void Run() { Process.Start(Exe); } static readonly string Exe = Environment.ProcessPath!; }")]
    [InlineData("class C { void Run() { Process.Start(Self()); } static string Self() => Environment.ProcessPath!; }")]
    [InlineData("var self = Environment.ProcessPath!; Process.Start($$\"\"\"{{self}}\"\"\");")]
    [InlineData("var self = Environment.ProcessPath!; Process.Start($$$\"\"\"{{{self}}}\"\"\");")]
    [InlineData("using static System.Environment; Process.Start(ProcessPath!);")]
    [InlineData("using E = System.Environment; Process.Start(E.ProcessPath!);")]
    [InlineData("var (exe, _) = (Environment.ProcessPath!, 1); Process.Start(exe);")]
    [InlineData("var (n, exe) = (1, Environment.ProcessPath!); Process.Start(exe);")]
    [InlineData("foreach (var exe in new[] { Environment.ProcessPath! }) { Process.Start(exe); }")]
    public void StartingTheToolsOwnBinaryIsAViolation(string source)
    {
        Assert.Equal(new[] { OwnBinary }, ViolationsOfHostsSource(source));
    }

    [Theory]
    [InlineData("if (Environment.ProcessPath is not null && Lookup() is { } git) { Process.Start(git); }")]
    [InlineData("if (Environment.ProcessPath is string { Length: > 0 } self && Lookup() is not { } git) { Process.Start(git); }")]
    [InlineData("var (exe, other) = (\"git\", Environment.ProcessPath!); Process.Start(exe);")]
    [InlineData("var self = Environment.ProcessPath!; Process.Start(\"git\", $$\"\"\"{self}\"\"\");")]
    [InlineData("var ProcessPath = \"git\"; Process.Start(ProcessPath);")]
    [InlineData("class C { void Run() { Process.Start(Git); } static string Self = Environment.ProcessPath!; static string Git = \"git\"; }")]
    [InlineData("class C { void Run() { Process.Start(Git()); } static string Self() => Environment.ProcessPath!; static string Git() => \"git\"; }")]
    [InlineData("foreach (var git in new[] { \"git\" }) { Process.Start(git); } var self = Environment.ProcessPath!;")]
    public void AnotherProgramBesideAnOwnPathBindingIsNoViolation(string source)
    {
        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void ASourceWithAnUpperCaseExtensionIsScanned()
    {
        using var planted = new PlantedSolution();
        planted.Project("Hosts");
        planted.Source("Hosts/Spawn.CS", "Process.Start(Environment.ProcessPath!);");

        Assert.Equal(new[] { "Hosts/Spawn.CS: starts the tool's own binary" }, SelfStart.Violations(planted.Root));
    }

    [Fact]
    public void AProjectWithAnUpperCaseExtensionIsScanned()
    {
        using var planted = new PlantedSolution();
        planted.Source("Hosts/Hosts.CSPROJ", "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>");
        planted.Source("Hosts/Spawn.cs", "Process.Start(Environment.ProcessPath!);");

        Assert.Equal(new[] { OwnBinary }, SelfStart.Violations(planted.Root));
    }

    [Theory]
    [InlineData("// Process.Start(Environment.ProcessPath!);")]
    [InlineData("/* Process.Start(Environment.ProcessPath!); */")]
    [InlineData("/// <summary>Process.Start(Environment.ProcessPath!);</summary>\nvar x = 1;")]
    public void ACommentThatNamesALaunchIsNoViolation(string source)
    {
        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void NamedArgumentsOfAnotherProgramAreNoViolation()
    {
        Assert.Empty(ViolationsOfHostsSource("Process.Start(arguments: \"agent-tools\", fileName: \"git\");"));
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
    public void AnUnwrappedAndChainedLaunchOfAnotherProgramIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath!; var exe = \"git\"; var alias = exe; Process.Start((alias)!);";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void ATargetTypedStartInfoForAnotherProgramIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath!; ProcessStartInfo info = new(\"git\"); Process.Start(info);";

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
    public void AnInitializerStartInfoForAnotherProgramIsNoViolation()
    {
        var source = "var self = new ProcessStartInfo(Environment.ProcessPath!); var info = new ProcessStartInfo(\"git\"); "
            + "using var p = new Process { StartInfo = info }; p.Start();";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void ABoundPathThatStartsAnotherProgramIsNoViolation()
    {
        var source = "if (Environment.ProcessPath is { } self) { Log(self); } if (Lookup() is { } git) { Process.Start(git); }";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void AnOwnPathNamedOnlyInsideAStringLiteralIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath!; Process.Start(\"git\", \"self {self} status\");";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void AnOwnPathInsideAnEscapedBraceIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath!; Process.Start(\"git\", $\"{{self}} status\");";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void AnExpressionOfAnotherProgramBesideTheOwnPathIsNoViolation()
    {
        var source = "var self = Environment.ProcessPath!; var dir = \"bin\"; Process.Start(Path.Combine(dir, \"git\"));";

        Assert.Empty(ViolationsOfHostsSource(source));
    }

    [Fact]
    public void SelfReferencingAssignmentsEndWithoutBlowingUp()
    {
        var source = "var a = a + a; var b = a + a; var c = b + b; var d = c + c; var e = d + d; Process.Start(e + e);";

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
