# The Mac Studio's memory budget: what the model may take and what is left for everything else.
# The host guide's `## Memory budget` explains the arithmetic; the declarations that must stay
# inside it (oMLX's ceiling, Colima's VM, the jetsam priority) read their numbers from here.
rec {
  # Physical memory of the host.
  totalGiB = 256;
  # The memory guard's fixed ceiling for the oMLX server.
  omlxCeilingGiB = 192;
  # How far the server's footprint may pass its ceiling before the budget stops holding.
  omlxOverCeilingGiB = 2;
  # The Colima VM's memory.
  colimaGiB = 8;
  # What the VM's host-side processes take beyond its memory.
  colimaOverheadGiB = 1;
  # Verification runs that may hold a slot at once, from the host declaration.
  verifySlots =
    (builtins.fromJSON (
      builtins.readFile ../../../home/common/agent-skills/host-declarations/eleven-m5.json
    )).verify_slots;
  # One verification run's memory (provisional, checked against the day line).
  verifyRunGiB = 6;
  # One CI job's memory (provisional, checked against the day line).
  ciJobGiB = 3;
  # What macOS and its daemons take (provisional, checked against the day line).
  macosGiB = 12;
  # The fseventsd share inside macosGiB, enforced by the trim daemon.
  fseventsdLimitGiB = 4;
  # Memory held back from every other use.
  floorGiB = 16;
  # What the model and the floor leave for Colima, verification, CI and macOS.
  othersBudgetGiB = totalGiB - omlxCeilingGiB - omlxOverCeilingGiB - floorGiB;
  # The oMLX daemon's jetsam priority; launchd gives every other daemon 40.
  omlxJetsamPriority = 100;
  # How often the fseventsd trim daemon restarts it.
  fseventsdRestartMinutes = 60;
}
