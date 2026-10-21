import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import JSZip from 'jszip';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const args = process.argv.slice(2);
const option = name => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const outputPath = option('--output');
if (!outputPath) throw new Error('Missing --output path');
let input = '';
for await (const chunk of process.stdin) input += chunk;
const payload = JSON.parse(input);
const C = { ink: '#17243A', muted: '#526078', header: '#223550', line: '#CBD5E1', pale: '#EDF2F7',
  due: '#FCE6E4', soon: '#FFF1C9', blue: '#3B6E9E', green: '#438575' };
const DATES = new Set(['Date Added', 'Deadline', 'Date Applied', 'Last Status Change', 'Follow-up Date',
  'Outreach Date', 'Replied Date', 'Last Contact', 'Last Checked', 'Research Date', 'First Response Date', 'First Interview Date']);
const DROPDOWNS = {
  applications: { Lane: 'Lane', Priority: 'Priority', Level: 'Level', Source: 'Source', Verdict: 'Verdict', Status: 'Status' },
  network: { Type: 'ContactType', Channel: 'Channel', Status: 'NetworkStatus' },
  targets: { Type: 'TargetType', Lane: 'Lane', Priority: 'Priority' },
};
const WIDTHS = { ID: 10, Company: 26, Organisation: 28, Role: 36, Name: 24, Notes: 66, 'Why Them': 46,
  'Their Role': 38, 'Next Best Action': 40, 'Next Action': 40, 'JD Link': 28, 'Careers URL': 28,
  'CV Version': 36, 'How Met': 48, LinkedIn: 28, Email: 30, 'Research File': 40, 'Assets Sent': 40,
  'Contact IDs': 18, 'Target ID': 14, 'First Response Date': 24, 'First Interview Date': 24 };
const NAMES = { applications: 'Applications', network: 'Network', targets: 'Targets' };
const RESPONDED = ['screening', 'interview_1', 'interview_2', 'offer', 'rejected'];
const INTERVIEWED = ['interview_1', 'interview_2', 'offer'];
const CONTACT_DUE = ['contacted', 'warm', 'to_contact'];
const excelDate = text => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text ?? '')) return null;
  const date = new Date(`${text}T00:00:00.000Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== text ? null : date;
};
const col = number => { let s = ''; while (number) { number--; s = String.fromCharCode(65 + number % 26) + s; number = Math.floor(number / 26); } return s; };
const safe = value => typeof value === 'string' && value.startsWith('=') ? `'${value}` : value;
const value = (field, raw) => raw === '' || raw == null ? null : DATES.has(field) ? excelDate(raw) ?? safe(raw) : field === 'Fit %' && Number.isFinite(Number(raw)) ? Number(raw) : safe(raw);

function base(sheet, address) {
  sheet.showGridLines = false;
  sheet.getRange(address).format.font = { name: 'Arial', size: 10, color: C.ink };
  sheet.getRange(address).format.verticalAlignment = 'center';
  sheet.getRange(address).format.rowHeight = 24;
}
function header(sheet, address) {
  sheet.getRange(address).format = { fill: C.header, font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', rowHeight: 30, wrapText: true };
  sheet.getRange(address).format.borders = { insideVertical: { style: 'thin', color: '#FFFFFF' } };
}
function section(sheet, row, text, end = 'B') {
  sheet.getRange(`A${row}`).values = [[text]];
  sheet.getRange(`A${row}:${end}${row}`).format = { fill: C.pale,
    font: { name: 'Arial', size: 10, bold: true, color: C.ink }, rowHeight: 28 };
}

function build(data, asOf = null) {
  const wb = Workbook.create();
  const dash = wb.worksheets.add('Dashboard');
  const sheets = Object.fromEntries(Object.entries(NAMES).map(([key, name]) => [key, wb.worksheets.add(name)]));
  const lists = wb.worksheets.add('Lists');
  dash.tabColor = C.header;
  const cap = Object.fromEntries(Object.keys(sheets).map(key => [key, Math.max(1001, data.rows[key].length + 1001)]));
  const columns = {}, listRefs = {}, keys = Object.keys(data.choices);
  base(lists, `A1:${col(keys.length + 4)}${Math.max(...Object.values(cap))}`);
  keys.forEach((key, i) => {
    const c = col(i + 1);
    lists.getRange(`${c}1`).values = [[key]];
    lists.getRange(`${c}2:${c}${data.choices[key].length + 1}`).values = data.choices[key].map(x => [x]);
    lists.getRange(`${c}1:${c}${data.choices[key].length + 1}`).format.columnWidth = Math.max(18, ...data.choices[key].map(x => x.length + 3));
    listRefs[key] = `'Lists'!$${c}$2:$${c}$${data.choices[key].length + 1}`;
  });
  header(lists, `A1:${col(keys.length)}1`);
  lists.freezePanes.freezeRows(1);
  for (const [key, sheet] of Object.entries(sheets)) {
    const fields = data.schema[key].fields, last = col(fields.length), bottom = Math.max(12, data.rows[key].length + 1);
    columns[key] = Object.fromEntries(fields.map((field, i) => [field, col(i + 1)]));
    base(sheet, `A1:${last}${bottom}`);
    sheet.getRange(`A1:${last}1`).values = [fields];
    header(sheet, `A1:${last}1`);
    if (data.rows[key].length) sheet.getRange(`A2:${last}${data.rows[key].length + 1}`).values = data.rows[key].map(row => fields.map(field => value(field, row[field])));
    fields.forEach((field, i) => {
      const c = col(i + 1);
      sheet.getRange(`${c}1:${c}${bottom}`).format.columnWidth = WIDTHS[field] ?? (DATES.has(field) ? 20 : 19);
      if (DATES.has(field)) sheet.getRange(`${c}2:${c}${cap[key]}`).setNumberFormat('dd mmm yyyy');
      if (field === 'Fit %') sheet.getRange(`${c}2:${c}${cap[key]}`).setNumberFormat('0"%"');
    });
    sheet.freezePanes.freezeRows(1);
    sheet.freezePanes.freezeColumns(3);
    const table = sheet.tables.add(`A1:${last}${Math.max(2, data.rows[key].length + 1)}`, true, `CareerOS${NAMES[key]}`);
    table.style = 'TableStyleLight1';
    table.showFilterButton = true;
    for (const [field, keyList] of Object.entries(DROPDOWNS[key])) {
      const c = columns[key][field];
      sheet.getRange(`${c}2:${c}${cap[key]}`).dataValidation = { rule: { type: 'list', formula1: listRefs[keyList] } };
    }
  }
  const A = columns.applications, N = columns.network;
  const appRange = `A2:${col(data.schema.applications.fields.length)}${cap.applications}`;
  sheets.applications.getRange(appRange).conditionalFormats.addCustom(`AND($${A.Status}2="applied",ISNUMBER($${A['Follow-up Date']}2),$${A['Follow-up Date']}2>0,$${A['Follow-up Date']}2<=TODAY())`, { fill: C.due });
  sheets.applications.getRange(appRange).conditionalFormats.addCustom(`AND(OR($${A.Status}2="shortlisted",$${A.Status}2="drafted"),ISNUMBER($${A.Deadline}2),$${A.Deadline}2>=TODAY(),$${A.Deadline}2<=TODAY()+7)`, { fill: C.soon });
  sheets.network.getRange(`A2:${col(data.schema.network.fields.length)}${cap.network}`).conditionalFormats.addCustom(`AND(OR(${CONTACT_DUE.map(s => `$${N.Status}2="${s}"`).join(',')}),ISNUMBER($${N['Follow-up Date']}2),$${N['Follow-up Date']}2>0,$${N['Follow-up Date']}2<=TODAY())`, { fill: C.due });
  const range = (key, field) => `'${NAMES[key]}'!$${columns[key][field]}$2:$${columns[key][field]}$${cap[key]}`;
  const S = f => range('applications', f), NS = f => range('network', f), TS = f => range('targets', f);
  const submitted = [S('Date Applied'), '">0"', S('Date Applied'), '"<="&$B$3'];
  const count = pairs => `COUNTIFS(${pairs.join(',')})`;
  const byStatus = (statuses, common, key = 'applications') => statuses.map(s => count([...common, range(key, 'Status'), `"${s}"`])).join('+');
  const historical = (dateRange, statuses, common = submitted) => `${count([...common, dateRange, '">0"', dateRange, '"<="&$B$3'])}+${byStatus(statuses, [...common, dateRange, '"="'])}`;
  const mature = [...submitted, S('Date Applied'), `"<="&($B$3-${data.constants.MATURE_DAYS})`];
  base(dash, 'A1:N95');
  dash.getRange('A1:A95').format.columnWidth = 53;
  dash.getRange('B1:D95').format.columnWidth = 16;
  dash.getRange('B1:D95').format.horizontalAlignment = 'right';
  dash.getRange('E1:E95').format.columnWidth = 3;
  dash.getRange('F1:N95').format.columnWidth = 12;
  dash.getRange('A2').values = [['CareerOS dashboard']];
  dash.getRange('A2').format.font = { name: 'Arial', size: 16, bold: true, color: C.ink };
  dash.getRange('A2:D2').format.borders = { bottom: { style: 'thin', color: C.line } };
  dash.getRange('A3').values = [['As of']];
  if (asOf) dash.getRange('B3').values = [[excelDate(asOf)]];
  else dash.getRange('B3').formulas = [['=TODAY()']];
  dash.getRange('B3').setNumberFormat('dd mmm yyyy');
  const cells = {};
  const metric = (row, label, formula, rate = false) => {
    dash.getRange(`A${row}`).values = [[label]];
    dash.getRange(`B${row}`).formulas = [[formula]];
    dash.getRange(`B${row}`).setNumberFormat(rate ? '0%' : '#,##0');
    cells[label] = `B${row}`;
  };
  section(dash, 5, 'Pipeline');
  metric(6, 'Roles logged', `=${count([S('ID'), '"<>"'])}`);
  metric(7, 'Shortlisted', `=${count([S('Status'), '"shortlisted"'])}`);
  metric(8, 'Drafted', `=${count([S('Status'), '"drafted"'])}`);
  metric(9, 'Applications sent', `=${count(submitted)}`);
  metric(10, 'Applications reaching interview', `=${historical(S('First Interview Date'), INTERVIEWED)}`);
  metric(11, 'Current offers', `=${count([...submitted, S('Status'), '"offer"'])}`);
  section(dash, 13, 'Conversion');
  metric(14, 'Mature applications (14+ days)', `=${count(mature)}`);
  metric(15, 'Responses from mature applications', `=${historical(S('First Response Date'), RESPONDED, mature)}`);
  metric(16, 'Response rate (sent 14+ days ago)', '=IF(B14=0,"n.a.",B15/B14)', true);
  metric(17, 'Interview rate', '=IF(B9=0,"n.a.",B10/B9)', true);
  metric(18, 'Contacts reached out to', `=${count([NS('Outreach Date'), '">0"', NS('Outreach Date'), '"<="&$B$3'])}`);
  metric(19, 'Replies from reached contacts', `=${count([NS('Outreach Date'), '">0"', NS('Outreach Date'), '"<="&$B$3', NS('Replied Date'), '">0"', NS('Replied Date'), '"<="&$B$3'])}`);
  metric(20, 'Outreach reply rate', '=IF(B18=0,"n.a.",B19/B18)', true);
  section(dash, 22, 'Actions');
  metric(23, 'Application follow-ups due', `=${count([...submitted, S('Status'), '"applied"', S('Follow-up Date'), '">0"', S('Follow-up Date'), '"<="&$B$3'])}`);
  metric(24, 'Deadlines in next 7 days (not sent)', `=${byStatus(['shortlisted', 'drafted'], [S('Deadline'), '">="&$B$3', S('Deadline'), '"<="&($B$3+7)'])}`);
  metric(25, 'Applied 21+ days without status change', `=${count([...submitted, S('Status'), '"applied"', S('Last Status Change'), '">0"', S('Last Status Change'), `"<="&($B$3-${data.constants.NO_RESPONSE_DAYS})`])}`);
  metric(26, 'Contact follow-ups due', `=${byStatus(CONTACT_DUE, [NS('Follow-up Date'), '">0"', NS('Follow-up Date'), '"<="&$B$3'], 'network')}`);
  metric(27, 'Targets researched', `=${count([TS('ID'), '"<>"', TS('Research File'), '"<>"'])}`);
  section(dash, 29, 'Next IDs');
  Object.keys(sheets).forEach((key, i) => {
    const helper = col(keys.length + 2 + i), pre = data.schema[key].prefix;
    lists.getRange(`${helper}1`).values = [[`${NAMES[key]} ID number`]];
    header(lists, `${helper}1`);
    lists.getRange(`${helper}1:${helper}${cap[key]}`).format.columnWidth = 26;
    lists.getRange(`${helper}2`).formulas = [[`=IF(LEFT('${NAMES[key]}'!A2,1)="${pre}",IFERROR(VALUE(MID('${NAMES[key]}'!A2,2,20)),0),0)`]];
    lists.getRange(`${helper}2:${helper}${cap[key]}`).fillDown();
    metric(30 + i, `Next ${key === 'applications' ? 'application' : key === 'network' ? 'contact' : 'target'} ID`, `="${pre}"&TEXT(MAX('Lists'!$${helper}$2:$${helper}$${cap[key]})+1,"000")`);
  });
  function breakdown(start, title, field, values) {
    section(dash, start, title, 'D');
    dash.getRange(`B${start}:D${start}`).values = [['Sent', 'Interviews', 'Interview rate']];
    values.forEach((text, i) => {
      const row = start + 1 + i, common = [...submitted, S(field), `$A${row}`];
      dash.getRange(`A${row}`).values = [[text]];
      dash.getRange(`B${row}:D${row}`).formulas = [[`=${count(common)}`, `=${historical(S('First Interview Date'), INTERVIEWED, common)}`, `=IF(B${row}=0,"n.a.",C${row}/B${row})`]];
      dash.getRange(`B${row}:C${row}`).setNumberFormat('#,##0');
      dash.getRange(`D${row}`).setNumberFormat('0%');
    });
    return start + values.length + 2;
  }
  const laneRow = 35;
  let next = breakdown(laneRow, 'By lane', 'Lane', data.choices.Lane);
  next = breakdown(next, 'By source', 'Source', data.choices.Source);
  next = breakdown(next, 'By verdict', 'Verdict', data.choices.Verdict);
  const statusRow = next;
  section(dash, statusRow, 'By current status');
  dash.getRange(`B${statusRow}`).values = [['Roles']];
  data.choices.Status.forEach((status, i) => {
    const row = statusRow + 1 + i;
    dash.getRange(`A${row}`).values = [[status]];
    dash.getRange(`B${row}`).formulas = [[`=${count([S('Status'), `$A${row}`])}`]];
  });
  const charts = data.rows.applications.length ? [
    [dash.charts.add('bar', dash.getRange(`A${statusRow}:B${statusRow + data.choices.Status.length}`)), 'Pipeline by current status', 'F5', 'N21'],
    [dash.charts.add('bar', dash.getRange(`A${laneRow}:C${laneRow + data.choices.Lane.length}`)), 'Sent and interviews by lane', 'F24', 'N39'],
  ] : [];
  charts.forEach(([chart, title, from, to], i) => {
    chart.title = title; chart.setPosition(from, to);
    chart.titleTextStyle.typeface = 'Arial'; chart.titleTextStyle.fontSize = 14;
    chart.hasLegend = i > 0;
    if (i) chart.legend = { position: 'top', textStyle: { typeface: 'Arial', fontSize: 11 } };
    chart.xAxis = { axisType: 'textAxis', textStyle: { typeface: 'Arial', fontSize: 11 } };
    chart.yAxis = { numberFormatCode: '0', numberFormatSourceLinked: false, textStyle: { typeface: 'Arial' } };
    chart.series.items.forEach((series, j) => { series.fill = j === 0 ? C.blue : C.green; });
  });
  if (!data.rows.applications.length) {
    dash.getRange('F5').values = [['No applications in this local snapshot']];
    dash.getRange('F5').format.font = { name: 'Arial', size: 10, color: C.muted, italic: true };
  }
  const notes = [
    ['Sources', 'Snapshot of local CareerOS Applications, Network and Targets CSVs. Live Google Sheets can contain newer records.'],
    ['Applications sent', 'A recorded Date Applied on or before the dashboard date. Status alone does not establish submission.'],
    ['Response history', 'First Response Date retains a response after later status changes. Legacy current response statuses also count when the first date is blank.'],
    ['Interview history', 'First Interview Date retains an interview after later status changes. Legacy interview or offer statuses also count when the first date is blank.'],
    ['Response rate', `Responses from applications sent at least ${data.constants.MATURE_DAYS} days ago divided by that same mature population.`],
    ['Outreach reply rate', 'Contacts with Outreach Date and Replied Date divided by contacts with Outreach Date. Blank dates are excluded.'],
    ['Refresh', 'Rebuild after local CSV changes. This export does not read or update live Google Sheets. Workbook edits need explicit import to update local CSVs.'],
    ['Range capacity', 'Formula and validation ranges reserve at least 1,000 additional rows per table. Rebuilding expands them to current rows plus 1,000.'],
    ['Missing dates', 'Blank dates stay blank. Text that is not a valid ISO date is preserved for correction and excluded from date metrics.'],
  ];
  const notesRow = Math.max(...keys.map(k => data.choices[k].length)) + 4;
  lists.getRange(`A${notesRow}:B${notesRow + notes.length}`).values = [['Definitions and source notes', null], ...notes];
  lists.getRange(`A${notesRow}:B${notesRow}`).format.font = { name: 'Arial', size: 10, bold: true, color: C.ink };
  // Explanatory prose spans the empty notes area without widening list columns.
  for (let row = notesRow + 1; row <= notesRow + notes.length; row++) {
    lists.mergeCells(`B${row}:J${row}`);
    lists.getRange(`B${row}:J${row}`).format.wrapText = true;
  }
  lists.getRange(`A${notesRow}:A${notesRow + notes.length}`).format.columnWidth = 30;
  wb.recalculate();
  return { wb, sheets, dash, lists, cells, cap, columns };
}

function expected(data, asOf) {
  const date = raw => excelDate(raw)?.toISOString().slice(0, 10);
  const valid = raw => { const d = date(raw); return Boolean(d && d <= asOf); };
  const day = n => new Date(new Date(`${asOf}T00:00:00Z`).getTime() + n * 86400000).toISOString().slice(0, 10);
  const sent = data.rows.applications.filter(r => valid(r['Date Applied']));
  const historic = (r, field, statuses) => valid(r[field]) || (!r[field] && statuses.includes(r.Status));
  const mature = sent.filter(r => r['Date Applied'] <= day(-data.constants.MATURE_DAYS));
  const interviewed = sent.filter(r => historic(r, 'First Interview Date', INTERVIEWED));
  const response = mature.filter(r => historic(r, 'First Response Date', RESPONDED));
  const outreach = data.rows.network.filter(r => valid(r['Outreach Date']));
  const replies = outreach.filter(r => valid(r['Replied Date']));
  const nextId = key => `${data.schema[key].prefix}${String(Math.max(0, ...data.rows[key].map(r => {
    const m = new RegExp(`^${data.schema[key].prefix}(\\d+)$`).exec(r.ID ?? ''); return m ? Number(m[1]) : 0;
  })) + 1).padStart(3, '0')}`;
  return {
    'Roles logged': data.rows.applications.filter(r => r.ID).length,
    Shortlisted: data.rows.applications.filter(r => r.Status === 'shortlisted').length,
    Drafted: data.rows.applications.filter(r => r.Status === 'drafted').length,
    'Applications sent': sent.length, 'Applications reaching interview': interviewed.length,
    'Current offers': sent.filter(r => r.Status === 'offer').length,
    'Mature applications (14+ days)': mature.length, 'Responses from mature applications': response.length,
    'Response rate (sent 14+ days ago)': mature.length ? response.length / mature.length : 'n.a.',
    'Interview rate': sent.length ? interviewed.length / sent.length : 'n.a.',
    'Contacts reached out to': outreach.length, 'Replies from reached contacts': replies.length,
    'Outreach reply rate': outreach.length ? replies.length / outreach.length : 'n.a.',
    'Application follow-ups due': sent.filter(r => r.Status === 'applied' && valid(r['Follow-up Date'])).length,
    'Deadlines in next 7 days (not sent)': data.rows.applications.filter(r => ['shortlisted', 'drafted'].includes(r.Status) && date(r.Deadline) >= asOf && date(r.Deadline) <= day(7)).length,
    'Applied 21+ days without status change': sent.filter(r => r.Status === 'applied' && valid(r['Last Status Change']) && r['Last Status Change'] <= day(-data.constants.NO_RESPONSE_DAYS)).length,
    'Contact follow-ups due': data.rows.network.filter(r => CONTACT_DUE.includes(r.Status) && valid(r['Follow-up Date'])).length,
    'Targets researched': data.rows.targets.filter(r => r.ID && r['Research File']).length,
    'Next application ID': nextId('applications'), 'Next contact ID': nextId('network'), 'Next target ID': nextId('targets'),
  };
}
function check(built, data, asOf) {
  const metrics = expected(data, asOf);
  for (const [label, wanted] of Object.entries(metrics)) {
    const actual = built.dash.getRange(built.cells[label]).values[0][0];
    if (typeof wanted === 'number' ? typeof actual !== 'number' || Math.abs(actual - wanted) > 1e-9 : actual !== wanted)
      throw new Error(`${label}: expected ${JSON.stringify(wanted)}, got ${JSON.stringify(actual)}`);
  }
  return metrics;
}
async function selfTest() {
  const data = structuredClone(payload);
  const a = (id, status, applied = '', extra = {}) => ({ ID: id, Company: 'Fixture only', Role: id, Status: status, 'Date Applied': applied, Lane: 'Content & Social', ...extra });
  data.rows = { applications: [
    a('A002', 'applied', '2026-09-01'), a('A010', 'rejected'),
    a('A011', 'rejected', '2026-09-01', { 'First Response Date': '2026-09-04', 'First Interview Date': '2026-09-08' }),
    a('A012', 'withdrawn', '2026-09-01', { 'First Response Date': '2026-09-03', 'First Interview Date': '2026-09-05' }),
    a('A013', 'applied', '2026-10-20', { 'Follow-up Date': '2026-10-21', 'Last Status Change': '2026-10-20' }),
    a('A014', 'applied', '2026-09-01', { 'Follow-up Date': '2026-10-20', 'Last Status Change': '2026-09-01' }),
    a('A015', 'shortlisted', '', { Deadline: '2026-10-28' }), a('A016', 'drafted', '', { Deadline: '2026-10-29' }),
    a('A017', 'offer', '2026-10-01'), a('A018', 'applied', '2026-10-07'),
    a('A019', 'applied', '2026-10-08'), a('A020', 'applied', '2026-11-01'),
    a('A021', 'applied', '2026-02-30', { 'Follow-up Date': 'invalid' }),
  ], network: [
    { ID: 'N002', Name: 'Fixture contact', Status: 'warm' },
    { ID: 'N020', Name: 'Fixture contact', Status: 'contacted', 'Outreach Date': '2026-10-01', 'Follow-up Date': '2026-10-21' },
    { ID: 'N021', Name: 'Fixture contact', Status: 'replied', 'Outreach Date': '2026-10-01', 'Replied Date': '2026-10-02', 'Follow-up Date': '2026-10-20' },
    { ID: 'N022', Name: 'Fixture contact', Status: 'cold', 'Follow-up Date': '2026-10-20' },
    { ID: 'N023', Name: 'Fixture contact', Status: 'replied', 'Replied Date': '2026-10-20' },
  ], targets: [{ ID: 'T002', Organisation: 'Fixture only' }, { ID: 'T040', Organisation: 'Fixture only', 'Research File': 'fixture.md' }] };
  const built = build(data, '2026-10-21');
  check(built, data, '2026-10-21');
  built.sheets.applications.getRange(`${built.columns.applications['First Interview Date']}2`).values = [[excelDate('2026-10-10')]];
  built.wb.recalculate();
  if (built.dash.getRange(built.cells['Applications reaching interview']).values[0][0] !== 4) throw new Error('Input-edit recalculation failed');
  const newRow = data.rows.applications.length + 2, fields = data.schema.applications.fields, extension = a('A100', 'applied', '2026-10-01');
  built.sheets.applications.getRange(`A${newRow}:${col(fields.length)}${newRow}`).values = [fields.map(f => value(f, extension[f]))];
  built.wb.recalculate();
  if (built.dash.getRange(built.cells['Next application ID']).values[0][0] !== 'A101') throw new Error('Next-row max-ID update failed');
  if (built.dash.getRange(built.cells['Applications sent']).values[0][0] !== 9) throw new Error('Next-row sent count update failed');
  // Inspect the exported XML caches independently of the authoring engine.
  const fixtureFile = await SpreadsheetFile.exportXlsx(built.wb);
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'careeros-workbook-'));
  let archive;
  try {
    const fixturePath = path.join(temporary, 'fixture.xlsx');
    await fixtureFile.save(fixturePath);
    archive = await JSZip.loadAsync(await fs.readFile(fixturePath));
  } finally {
    await fs.rm(temporary, { recursive: true, force: true });
  }
  const dashboardXml = await archive.file('xl/worksheets/sheet1.xml').async('string');
  const cached = address => {
    const cell = dashboardXml.match(new RegExp(`<(?:\\w+:)?c\\b[^>]*\\br="${address}"[^>]*>[\\s\\S]*?<\\/(?:\\w+:)?c>`))?.[0];
    return cell?.match(/<(?:\w+:)?v>([^<]*)<\/(?:\w+:)?v>/)?.[1];
  };
  for (const [cell, wanted] of Object.entries({ B9: '9', B10: '4', B23: '2', B30: 'A101', B31: 'N024', B32: 'T041' })) {
    if (cached(cell) !== wanted) throw new Error(`Export cache ${cell}: expected ${wanted}, got ${cached(cell)}`);
  }
  const chartFiles = Object.keys(archive.files).filter(name => /(?:^|\/)charts\/[^/]+\.xml$/.test(name));
  if (chartFiles.length !== 2) throw new Error(`Expected two native fixture charts, found ${JSON.stringify(chartFiles)}`);
  const chartXml = (await Promise.all(chartFiles.map(name => archive.file(name).async('string')))).join('');
  if (!chartXml.includes('3B6E9E') || !chartXml.includes('438575')) throw new Error('Native chart series colours missing');
  const previewDir = option('--preview-dir');
  if (previewDir) {
    await fs.mkdir(previewDir, { recursive: true });
    const preview = await built.wb.render({ sheetName: 'Dashboard', range: 'A1:N39', scale: 1, format: 'png' });
    await fs.writeFile(path.join(previewDir, 'fixture-dashboard.png'), new Uint8Array(await preview.arrayBuffer()));
  }
  const empty = structuredClone(data); empty.rows = { applications: [], network: [], targets: [] };
  check(build(empty, '2026-10-21'), empty, '2026-10-21');
  console.log('Workbook fixtures passed: history, blank dates, submission evidence, cutoffs, max IDs, extension, input recalculation, exported caches and native chart colours.');
}

if (args.includes('--self-test')) await selfTest();
if (args.includes('--test-only')) process.exit(0);
const built = build(payload);
const asOf = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const metrics = check(built, payload, asOf);
const inspection = await built.wb.inspect({ kind: 'table', range: 'Dashboard!A2:D32', include: 'values,formulas', tableMaxRows: 32, tableMaxCols: 4, maxChars: 3500 });
const errors = await built.wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 20 }, summary: 'Final formula error scan', maxChars: 3000 });
if (/#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!|SPILL!|CALC!)/.test(errors.ndjson)) throw new Error(`Formula errors: ${errors.ndjson}`);
const previewDir = option('--preview-dir');
if (previewDir) {
  await fs.mkdir(previewDir, { recursive: true });
  const ranges = { Dashboard: ['Dashboard', 'A1:N39'], Applications: ['Applications', 'A1:H12'], ApplicationDates: ['Applications', 'I1:X12'], Network: ['Network', 'A1:F12'], NetworkDates: ['Network', 'K1:S12'], Targets: ['Targets', 'A1:G12'], TargetNotes: ['Targets', 'H1:M12'], Lists: ['Lists', 'A1:J24'] };
  for (const [name, [sheetName, range]] of Object.entries(ranges)) {
    const preview = await built.wb.render({ sheetName, range, scale: 1.5, format: 'png' });
    await fs.writeFile(path.join(previewDir, `${name}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  await fs.writeFile(path.join(previewDir, 'verification.json'), JSON.stringify({ asOf, metrics, capacity: built.cap, inspection: inspection.ndjson, formulaErrors: errors.ndjson }, null, 2));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(built.wb); await output.save(outputPath);
console.log(JSON.stringify({ saved: outputPath, counts: Object.fromEntries(Object.entries(payload.rows).map(([key, rows]) => [key, rows.length])), metrics, formulaScan: 'passed', previews: previewDir ?? null }));
