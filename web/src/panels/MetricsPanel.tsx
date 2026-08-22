/** Port of MetricsPanel: read-only figures, grouped exactly as in Qt. */

interface MetricsPanelProps {
  groups: Array<{ title: string; rows: Array<[string, string]> }>;
}

export function MetricsPanel({ groups }: MetricsPanelProps) {
  return (
    <>
      {groups.map((group) => (
        <fieldset className="group" key={group.title}>
          <legend>{group.title}</legend>
          {group.rows.map(([key, value]) => (
            <div className="row row-metric" key={key}>
              <span>{key}</span>
              <span className="metric-value">{value}</span>
            </div>
          ))}
        </fieldset>
      ))}
    </>
  );
}
