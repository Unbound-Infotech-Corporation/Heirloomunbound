import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, Upload, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

/**
 * Contacts sub-panel used inside MobileCall.
 *
 * - Lists contacts alphabetically.
 * - Tap a row → `onDial(contact)` (parent places the Twin outbound call).
 * - Add form (name + phone) inline.
 * - vCard (.vcf) upload button — server-side parser fans out to individual
 *   contacts and reports how many landed.
 */
export default function ContactsPanel({ onDial, disabled }) {
  const [contacts, setContacts] = useState([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef(null);

  const load = async () => {
    try {
      const { data } = await api.get("/contacts");
      setContacts(data.contacts || []);
    } catch { /* ignore */ }
  };

  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !phone.trim()) return;
    setAdding(true);
    try {
      await api.post("/contacts", { name, phone });
      setName(""); setPhone("");
      await load();
      toast.success("Contact added");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't add");
    } finally { setAdding(false); }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/contacts/${id}`);
      setContacts((cs) => cs.filter((c) => c.contact_id !== id));
    } catch { toast.error("Couldn't remove"); }
  };

  const onVcard = async (evt) => {
    const file = evt.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/contacts/import-vcard", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Imported ${data.imported} contact${data.imported === 1 ? "" : "s"}`);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "vCard import failed");
    } finally {
      setImporting(false);
      evt.target.value = "";
    }
  };

  return (
    <div data-testid="contacts-panel" className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="overline">Contacts</div>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={importing}
          data-testid="contacts-import-btn"
          className="text-xs px-2.5 py-1 rounded-sm border inline-flex items-center gap-1"
          style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
        >
          <Upload className="w-3 h-3" /> {importing ? "importing…" : "Import vCard"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".vcf,text/vcard,text/x-vcard,text/directory"
          onChange={onVcard}
          className="hidden"
          data-testid="contacts-import-input"
        />
      </div>

      <form
        onSubmit={submit}
        className="flex items-stretch gap-2"
        data-testid="contacts-add-form"
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name"
          className="flex-1 min-w-0 px-3 py-2 text-sm rounded-sm border"
          style={{ background: "var(--surface)", borderColor: "var(--border-default)", color: "var(--text-primary)" }}
          data-testid="contact-name-input"
        />
        <input
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="+1…"
          className="w-32 px-3 py-2 text-sm rounded-sm border"
          style={{ background: "var(--surface)", borderColor: "var(--border-default)", color: "var(--text-primary)" }}
          data-testid="contact-phone-input"
        />
        <button
          type="submit"
          disabled={adding}
          className="px-3 rounded-sm inline-flex items-center justify-center"
          style={{ background: "var(--accent)", color: "var(--surface)" }}
          data-testid="contact-add-btn"
        >
          <Plus className="w-4 h-4" />
        </button>
      </form>

      {contacts.length === 0 ? (
        <div
          className="text-sm py-6 text-center rounded-sm border border-dashed"
          style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
          data-testid="contacts-empty"
        >
          <UserPlus className="w-5 h-5 mx-auto mb-2 opacity-60" />
          No one saved yet.
        </div>
      ) : (
        <ul
          className="rounded-md border divide-y overflow-hidden"
          style={{ background: "var(--surface)", borderColor: "var(--border-default)" }}
          data-testid="contacts-list"
        >
          {contacts.map((c) => (
            <li key={c.contact_id} className="flex items-center gap-2 px-3 py-2.5">
              <button
                onClick={() => !disabled && onDial(c)}
                disabled={disabled}
                data-testid={`contact-dial-${c.contact_id}`}
                className="flex-1 text-left min-w-0"
              >
                <div className="text-sm truncate" style={{ color: "var(--text-primary)" }}>
                  {c.name}
                </div>
                <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                  {c.phone}
                </div>
              </button>
              <button
                onClick={() => remove(c.contact_id)}
                data-testid={`contact-remove-${c.contact_id}`}
                className="w-8 h-8 flex items-center justify-center rounded-sm"
                style={{ color: "var(--text-muted)" }}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
