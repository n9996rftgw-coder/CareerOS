// Render a CareerOS CV JSON into an ATS-safe .docx. Usage: node render_docx.js cv.json out.docx
const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, AlignmentType, LevelFormat, TabStopType, BorderStyle } = require("docx");

const cv = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = process.argv[3];
const FONT = "Calibri";
const COMPACT = !!cv.compact;
const BODY = COMPACT ? 20 : 21;
const RIGHT = cv.compact ? 10106 : 9638; // A4 text width in DXA with 1134 (2cm) margins

const run = (text, o = {}) => new TextRun({ text, font: FONT, size: o.size || BODY, bold: o.bold, italics: o.italics });
const heading = (text) => new Paragraph({
  spacing: COMPACT ? { before: 120, after: 40 } : { before: 200, after: 80 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "444444", space: 2 } },
  children: [run(text.toUpperCase(), { bold: true, size: 22 })],
});
const bullet = (text) => new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: COMPACT ? 0 : 40 }, children: [run(text)] });
const line = (left, right, o = {}) => new Paragraph({
  tabStops: [{ type: TabStopType.RIGHT, position: RIGHT }],
  spacing: { before: o.before || 0, after: 20 },
  children: [run(left, { bold: o.bold, italics: o.italics }), ...(right ? [run("\t" + right, { bold: o.bold })] : [])],
});

const p = cv.profile;
const contact = [p.city, p.phone, p.email, p.linkedin, p.portfolio].filter(Boolean).join("  |  ");
const kids = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, children: [run(p.name, { bold: true, size: 32 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [run(contact, { size: 20 })] }),
  heading("Professional Summary"),
  new Paragraph({ spacing: { after: 60 }, children: [run(cv.summary.text)] }),
  heading("Core Skills"),
  new Paragraph({ spacing: { after: 60 }, children: [run(cv.skills.join(", "))] }),
];
[["experience", "Experience"], ["projects", "Live Industry Projects"]].forEach(([sec, label]) => {
  const rs = cv.roles.filter((r) => (r.section || "experience") === sec);
  if (!rs.length) return;
  kids.push(heading(label));
  rs.forEach((r, i) => {
    if (COMPACT) {
      const title = r.title.replace(", Queen Mary University of London", "");
      kids.push(new Paragraph({ tabStops: [{ type: TabStopType.RIGHT, position: RIGHT }], spacing: { before: i ? 60 : 30, after: 0 },
        children: [run(r.employer, { bold: true }), run("  |  " + title + ", " + r.location, { italics: true }), run("\t" + r.dates, { bold: true })] }));
    } else {
      kids.push(line(r.employer, r.dates, { bold: true, before: i ? 140 : 40 }));
      kids.push(line(`${r.title}, ${r.location}`, "", { italics: true }));
    }
    r.bullets.forEach((b) => kids.push(bullet(b.text)));
  });
});
kids.push(heading("Education"));
cv.education.forEach((e) => {
  kids.push(line(`${e.award}, ${e.institution}`, `${e.start} – ${e.end}`, { bold: true, before: 40 }));
  if (e.detail) kids.push(new Paragraph({ spacing: { after: COMPACT ? 0 : 40 }, children: [run(e.detail)] }));
});
if (COMPACT) {
  kids.push(heading("Certifications & Awards"));
  kids.push(new Paragraph({ spacing: { after: 20 }, children: [run("Certifications: ", { bold: true }), run(cv.certifications.join("; "))] }));
  kids.push(new Paragraph({ spacing: { after: 20 }, children: [run("Awards: ", { bold: true }), run(cv.awards.join("; "))] }));
} else {
  kids.push(heading("Certifications"));
  cv.certifications.forEach((c) => kids.push(bullet(c)));
  kids.push(heading("Awards"));
  cv.awards.forEach((a) => kids.push(bullet(a)));
}

const doc = new Document({
  creator: p.name,
  title: `${p.name} CV`,
  numbering: { config: [{ reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [{ properties: { page: { margin: COMPACT ? { top: 720, bottom: 720, left: 900, right: 900 } : { top: 1000, bottom: 1000, left: 1134, right: 1134 } } }, children: kids }],
});
Packer.toBuffer(doc).then((buf) => fs.writeFileSync(out, buf));
