const SHEET_ID = '1a9ahW9brvGS6B2QMDgUwRQmLRXiHDKecX4G-oZ8acFQ';
const TRADES_SHEET = 'Trades';
const AUDIT_SHEET = 'Audit Log';

const TRADE_HEADERS = [
  'id',
  'date',
  'side',
  'symbol',
  'fmp_symbol',
  'name',
  'quantity',
  'price',
  'currency',
  'fee',
  'note',
  'source',
  'created_by',
  'created_at'
];

const AUDIT_HEADERS = [
  'timestamp',
  'user',
  'action',
  'symbol',
  'side',
  'quantity',
  'price',
  'note'
];

function ok(payload) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, ...payload }))
    .setMimeType(ContentService.MimeType.JSON);
}

function fail(error) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: false, error: String(error) }))
    .setMimeType(ContentService.MimeType.JSON);
}

function checkToken(body) {
  const expected = PropertiesService.getScriptProperties().getProperty('APP_TOKEN');
  if (!expected) {
    throw new Error('APP_TOKEN script property is not set.');
  }
  if (String(body.token || '') !== String(expected)) {
    throw new Error('Invalid token.');
  }
}

function getSheet(name, headers) {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
  }
  const firstRow = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
  const hasHeader = firstRow.some(value => String(value || '').trim() !== '');
  if (!hasHeader) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function readRows(name, headers) {
  const sheet = getSheet(name, headers);
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return [];
  }
  const values = sheet.getRange(2, 1, lastRow - 1, headers.length).getValues();
  return values
    .filter(row => row.some(value => String(value || '').trim() !== ''))
    .map(row => {
      const item = {};
      headers.forEach((header, i) => {
        const value = row[i];
        item[header] = value instanceof Date ? Utilities.formatDate(value, 'Etc/UTC', "yyyy-MM-dd'T'HH:mm:ss'Z'") : value;
      });
      return item;
    });
}

function appendRow(name, headers, item) {
  const sheet = getSheet(name, headers);
  const row = headers.map(header => item && item[header] !== undefined ? item[header] : '');
  sheet.appendRow(row);
}

function doGet() {
  try {
    getSheet(TRADES_SHEET, TRADE_HEADERS);
    getSheet(AUDIT_SHEET, AUDIT_HEADERS);
    return ok({ message: 'Equity PnL Apps Script is ready.' });
  } catch (err) {
    return fail(err);
  }
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents || '{}');
    checkToken(body);
    const action = String(body.action || '');

    if (action === 'setup') {
      getSheet(TRADES_SHEET, TRADE_HEADERS);
      getSheet(AUDIT_SHEET, AUDIT_HEADERS);
      return ok({ message: 'Sheets are ready.' });
    }

    if (action === 'read_trades') {
      return ok({ rows: readRows(TRADES_SHEET, TRADE_HEADERS) });
    }

    if (action === 'read_audit') {
      return ok({ rows: readRows(AUDIT_SHEET, AUDIT_HEADERS) });
    }

    if (action === 'append_trade') {
      appendRow(TRADES_SHEET, TRADE_HEADERS, body.trade || {});
      if (body.audit) {
        appendRow(AUDIT_SHEET, AUDIT_HEADERS, body.audit);
      }
      return ok({ message: 'Trade appended.' });
    }

    throw new Error(`Unknown action: ${action}`);
  } catch (err) {
    return fail(err);
  }
}
