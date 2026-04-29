export function renderAnnotatedText(text, annotations) {
  if (!annotations.length) {
    return text;
  }

  const safeAnnotations = [...annotations]
    .filter(
      (annotation) =>
        Number.isInteger(annotation.start) &&
        Number.isInteger(annotation.end) &&
        annotation.start >= 0 &&
        annotation.end <= text.length &&
        annotation.end > annotation.start,
    )
    .sort((left, right) => left.start - right.start);

  if (!safeAnnotations.length) {
    return text;
  }

  const fragments = [];
  let currentIndex = 0;

  safeAnnotations.forEach((annotation, index) => {
    if (annotation.start > currentIndex) {
      fragments.push(text.slice(currentIndex, annotation.start));
    }

    const highlightedText = text.slice(annotation.start, annotation.end);
    fragments.push(
      <strong
        key={`annotation-${index}-${annotation.start}-${annotation.end}`}
        className="message-annotation"
        title={annotation.entity_id}
      >
        {highlightedText}
      </strong>,
    );
    currentIndex = annotation.end;
  });

  if (currentIndex < text.length) {
    fragments.push(text.slice(currentIndex));
  }

  return fragments;
}
