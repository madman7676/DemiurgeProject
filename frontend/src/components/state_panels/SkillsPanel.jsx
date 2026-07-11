import { getVisibleSkills } from "./skillsPanelUtils";

export function SkillsPanel({ skills }) {
  const visibleSkills = getVisibleSkills(skills);

  return (
    <section className="panel">
      <h2>Skills</h2>
      {visibleSkills.length === 0 ? (
        <p>No skills.</p>
      ) : (
        <ul className="skill-list">
          {visibleSkills.map((skill) => (
            <li key={skill.id} className="skill-card">
              <div className="skill-card-header">
                <span className="item-icon">{skill.icon || "*"}</span>
                <strong>{skill.name || skill.id}</strong>
                <span className="skill-level">Lv.{skill.level || 1}</span>
              </div>
              <div className="progress-row">
                <div className="progress-bar" aria-hidden="true">
                  <span
                    className="progress-segment progress-current"
                    style={{ width: `${clampPercent(skill.progress || 0)}%` }}
                  />
                </div>
                <span className="progress-value">{clampPercent(skill.progress || 0)}%</span>
              </div>
              {skill.description ? (
                <p className="skill-description">{skill.description}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function clampPercent(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return 0;
  }
  return Math.min(99, Math.max(0, numericValue));
}
