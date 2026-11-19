export const commands = {
  selftest: "python3 main.py --selftest",
  render: "python3 main.py --bv <BV号>",
  fetchAt: "python3 main.py --at",
  renderAndSend: "python3 main.py --bv <BV号> --send",
  loop: "python3 main.py --loop",
  browserCheck: "python3 main.py --browser-check",
} as const;

export const artifacts = {
  card: "out/card.png",
  db: "data/bili_note.db",
  logs: "logs/",
} as const;
