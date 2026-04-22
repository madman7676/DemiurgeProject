function pad(value) {
  return String(value).padStart(2, "0");
}

export function formatGameDateTime(
  gameTime,
  options = { hourCycle: "24h", dateStyle: "long" }
) {
  if (!gameTime) {
    return "Unknown time";
  }

  const hour =
    options.hourCycle === "12h"
      ? ((gameTime.hour + 11) % 12) + 1
      : gameTime.hour;
  const suffix =
    options.hourCycle === "12h" ? (gameTime.hour >= 12 ? " PM" : " AM") : "";

  if (options.dateStyle === "short") {
    return `${pad(gameTime.day)}/${pad(gameTime.month)}/${String(
      gameTime.year
    ).padStart(4, "0")} ${pad(hour)}:${pad(gameTime.minute)}${suffix}`;
  }

  return `Year ${gameTime.year}, Month ${gameTime.month}, Day ${
    gameTime.day
  } at ${pad(hour)}:${pad(gameTime.minute)}${suffix}`;
}

