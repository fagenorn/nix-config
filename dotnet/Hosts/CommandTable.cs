using System.CommandLine;
using System.Text.Json;

namespace AgentTools.Hosts;

public static class CommandTable
{
    public static IReadOnlyList<string> Ids { get; } = Build(TextWriter.Null)
        .Subcommands
        .Select(command => command.Name)
        .Order(StringComparer.Ordinal)
        .ToArray();

    public static RootCommand Build(TextWriter output)
    {
        var json = new Option<bool>("--json")
        {
            Description = "Write the listing as a JSON array",
        };
        var commands = new Command("commands", "List the command table") { json };
        commands.SetAction(parse =>
        {
            if (parse.GetValue(json))
            {
                output.WriteLine(JsonSerializer.Serialize(Ids));
                return 0;
            }

            foreach (var id in Ids)
            {
                output.WriteLine(id);
            }

            return 0;
        });

        return new RootCommand("The agent helper command line") { commands };
    }
}
