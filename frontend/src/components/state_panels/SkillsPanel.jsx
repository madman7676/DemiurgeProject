// Visible player skills list. Skills have no levels in Lite.
export function SkillsPanel({ skills }) {
  return (
    <section className="panel">
      <h2>Skills</h2>
      {skills.length === 0 ? (
        <p>No skills.</p>
      ) : (
        <ul className="data-list icon-list">
          {skills.map((skill) => (
            <li key={skill.id}>
              <span className="item-icon">{skill.icon || "*"}</span>
              <span>{skill.name || skill.id}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
