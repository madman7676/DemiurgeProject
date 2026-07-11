export function getVisibleSkills(skills) {
  return Array.isArray(skills)
    ? skills.filter((skill) => Number(skill?.level || 0) > 0)
    : [];
}
