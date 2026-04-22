// Visible player skills list.
export function SkillsPanel({ skills }) {
  return (
    <section className="panel">
      <h2>Skills</h2>
      {skills.length === 0 ? (
        <p>No skills available.</p>
      ) : (
        <ul className="data-list">
          {skills.map((skill) => (
            <li key={skill.skill_id}>
              {skill.name}: {skill.level}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
