export const dynamic = "force-dynamic";
import { factDictionaryData } from "../../lib/queries";

export default async function DataDictionary() {
  const rows = await factDictionaryData();
  return <><div className="top"><div><h2>Master data dictionary</h2><p className="muted">Every cataloged dashboard label, meaning, source, and handling rule. Typed source tables remain authoritative.</p></div></div><div className="panel dictionary-table table-wrap"><table><thead><tr><th>Dashboard label</th><th>Meaning</th><th>Class</th><th>Source</th><th>Source field</th><th>Method</th><th>Missing means</th><th>Scoring</th></tr></thead><tbody>{rows.map((row:any)=><tr key={row.field_key}><td><b>{row.display_label}</b><br/><small>{row.field_key}</small></td><td>{row.short_definition}</td><td>{row.data_class}</td><td>{row.primary_source_type}</td><td>{row.form_item || row.primary_source_field || "—"}</td><td>{row.extraction_method}</td><td>{row.null_meaning}</td><td>{row.used_in_scoring ? "Yes" : "No"}</td></tr>)}</tbody></table></div></>;
}
