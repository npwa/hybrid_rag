export function Planned({ title, milestone, text }: { title: string; milestone: string; text: string }) {
  return (
    <section className="card planned" aria-labelledby="planned-title">
      <h2 id="planned-title">{title}</h2>
      <p>{text}</p>
      <p className="muted">Not built yet: planned for milestone {milestone} (see Doc/step-9-plan.md).</p>
    </section>
  );
}
