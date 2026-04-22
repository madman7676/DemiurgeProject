import { formatGameDateTime } from "../../utils/formatGameTime";

// Time panel keeps display formatting in the frontend layer.
export function TimePanel({ currentTime, nearbyNpcs }) {
  return (
    <section className="panel">
      <h2>Time</h2>
      <p>{formatGameDateTime(currentTime)}</p>
      <p className="panel-note">
        Nearby NPCs:{" "}
        {nearbyNpcs.length > 0
          ? nearbyNpcs.map((npc) => npc.identity.name).join(", ")
          : "None"}
      </p>
    </section>
  );
}
