const ENTITY_MARKER_PATTERN = /\[\[([^\|\]]+)\|([^\]]+)\]\]/g;

export function renderNarrationWithEntities(text) {
  if (!text || !text.includes("[[")) {
    return text;
  }

  try {
    return parseEntityMarkers(text);
  } catch {
    return text;
  }
}

function parseEntityMarkers(text) {
  const fragments = [];
  let currentIndex = 0;
  let markerIndex = 0;

  for (const match of text.matchAll(ENTITY_MARKER_PATTERN)) {
    const [fullMatch, markerType, visibleText] = match;
    const startIndex = match.index;

    if (startIndex > currentIndex) {
      fragments.push(text.slice(currentIndex, startIndex));
    }

    fragments.push(renderEntityMarker(markerType, visibleText, markerIndex));
    currentIndex = startIndex + fullMatch.length;
    markerIndex += 1;
  }

  if (markerIndex === 0) {
    return text;
  }

  if (currentIndex < text.length) {
    fragments.push(text.slice(currentIndex));
  }

  return fragments;
}

function renderEntityMarker(markerType, visibleText, markerIndex) {
  const [entityType, entitySubtype = ""] = markerType.split(":");
  const key = `narration-entity-${markerIndex}`;

  if (markerType === "scene_entity:available" || markerType.startsWith("entity:")) {
    const pieces = visibleText.split("|");
    const label = markerType.startsWith("entity:") ? pieces[1] || pieces[0] : visibleText;
    return (
      <strong
        key={key}
        data-entity-type={entityType}
        data-entity-subtype={entitySubtype}
      >
        {label}
      </strong>
    );
  }

  if (markerType === "reference:known_reference") {
    return (
      <em
        key={key}
        data-entity-type={entityType}
        data-entity-subtype={entitySubtype}
      >
        {visibleText}
      </em>
    );
  }

  if (markerType === "player_change" || markerType === "scene_change") {
    return null;
  }

  return visibleText;
}
