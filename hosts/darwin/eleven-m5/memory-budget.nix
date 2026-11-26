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
  # No verify tree passed 1.7 GiB when measured, so 3 pays for four slots.
  verifyRunGiB = 3;
  # One CI job's memory (provisional, checked against the day line).
  ciJobGiB = 3;
  # What macOS and its daemons take (provisional, checked against the day line).
  macosGiB = 12;
  # The fseventsd share inside macosGiB, enforced by the trim daemon.
  fseventsdLimitGiB = 4;
  # What the agent's Claude sessions take together (4.5 GiB at the 24 Nov panic).
  agentSessionsGiB = 5;
  # Memory held back from every other use.
  floorGiB = 10;
  # Consecutive samples under the floor before the floor daemon ends a workload.
  floorSamples = 3;
  # Seconds a workload gets to exit on SIGTERM before SIGKILL.
  floorGraceSeconds = 5;
  # How far above the floor the floor daemon samples at the fast interval.
  floorMarginGiB = 16;
  # A fall in available memory between two samples that also earns the fast interval.
  floorFallGiB = 2;
  # The smallest workload the floor daemon may end: a smaller tree frees too little to matter.
  floorMinTreeGiB = 1;
  # The floor daemon's sampling interval near the floor or while memory falls.
  fastSampleSeconds = 2;
  # The floor daemon's sampling interval otherwise.
  slowSampleSeconds = 10;
  # The footprint over which one workload is ended whatever memory is free.
  runBoundGiB = 24;
  # What the model and the floor leave for Colima, verification, CI and macOS.
  othersBudgetGiB = totalGiB - omlxCeilingGiB - omlxOverCeilingGiB - floorGiB;
  # The oMLX daemon's jetsam priority, above the kernel's default band (180, JETSAM_PRIORITY_DEFAULT), so
  # jetsam ends the agents' default-band processes first; memory-floor refuses values outside 181-210.
  omlxJetsamPriority = 190;
  # How often the fseventsd trim daemon restarts it.
  fseventsdRestartMinutes = 60;
}
