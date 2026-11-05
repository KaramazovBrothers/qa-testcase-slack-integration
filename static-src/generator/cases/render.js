import { $, state } from '../store.js';
import { translate } from '../translations/translations.js';

const copyStatusTimers = new WeakMap();

/** Read the editable case card back into a plain record. */
export function readCase(card) {
  return {
    title: card.querySelector('h3').textContent,
    text: card.querySelector('pre').textContent,
    comment: card.querySelector('.case-comment').value.trim(),
    request_text: card.querySelector('.case-request').value.trim(),
  };
}

/** Clipboard text for one card, matching the Slack message layout. */
export function caseCopyText(card) {
  const item = readCase(card);
  return item.title + '\n\n' + item.text
    + (item.comment ? '\n\nДополнительная информация:\n' + item.comment : '');
}

const caseLabel = () =>
  state.language === 'en' ? 'Copy case' : state.language === 'uk' ? 'Копіювати кейс' : 'Копировать кейс';

function element(tag, { className, text } = {}) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusLine(options = {}) {
  const node = element('div', { className: 'case-copy-status' });
  node.setAttribute('role', 'status');
  node.setAttribute('aria-live', 'polite');
  Object.assign(node.style, options);
  return node;
}

function textarea({ className, rows = 3, maxLength, placeholder, style }) {
  const node = element('textarea', { className });
  node.rows = rows;
  node.placeholder = placeholder || '';
  if (maxLength) node.maxLength = maxLength;
  Object.assign(node.style, style);
  return node;
}

/** Render the generated cases into the output container. */
export function renderCases(cases) {
  const output = $('output');
  output.innerHTML = '';
  $('count').textContent = String(cases.length);

  cases.forEach((item, index) => {
    const card = element('div', { className: 'case' });
    const heading = element('h3', { text: (index + 1) + '. ' + item.title });
    const body = element('pre', { text: item.text });

    const head = element('div', { className: 'case-head' });
    head.style.flexWrap = 'wrap';

    const copyButton = element('button', { className: 'secondary copy-case', text: caseLabel() });
    copyButton.type = 'button';
    copyButton.setAttribute('aria-label', caseLabel() + ' ' + (index + 1));

    const slackButton = element('button', {
      className: 'send-case-slack',
      text: translate('Отправить в Slack'),
    });
    slackButton.type = 'button';
    slackButton.setAttribute('aria-label', translate('Отправить в Slack кейс ') + (index + 1));

    const editButton = element('button', { className: 'secondary', text: translate('Редактировать') });
    editButton.type = 'button';
    editButton.setAttribute('aria-pressed', 'false');
    editButton.addEventListener('click', () => {
      const editing = editButton.getAttribute('aria-pressed') !== 'true';
      editButton.setAttribute('aria-pressed', String(editing));
      editButton.textContent = translate(editing ? 'Готово' : 'Редактировать');
      [heading, body].forEach((node) => {
        node.contentEditable = editing ? 'plaintext-only' : 'false';
        node.style.outline = editing ? '2px solid #90b9fa' : '';
      });
      if (editing) body.focus();
    });

    const status = statusLine();

    const requestLabel = element('label', {
      text: translate('Обращение в Slack для этого кейса'),
    });
    const request = textarea({
      className: 'case-request',
      maxLength: 2000,
      style: {
        width: '100%',
        boxSizing: 'border-box',
        padding: '12px',
        border: '1px solid #bdccdc',
        borderRadius: '7px',
        font: 'inherit',
        resize: 'vertical',
      },
    });
    request.value = [
      translate($('integration').value === 'payout' ? 'Просьба провести тест выплаты.' : 'Просьба провести тест депозита.'),
      item.title,
    ].filter(Boolean).join('\n');
    requestLabel.appendChild(request);

    const commentLabel = element('label', {
      text: translate('Дополнительные инструкции (необязательно)'),
    });
    commentLabel.style.marginTop = '16px';
    const comment = textarea({
      className: 'case-comment',
      placeholder: translate('Будут отправлены в тред под описанием кейса'),
      style: {
        width: '100%',
        padding: '12px',
        border: '1px solid #bdccdc',
        borderRadius: '7px',
        font: 'inherit',
        resize: 'vertical',
      },
    });
    commentLabel.appendChild(comment);

    copyButton.addEventListener('click', () => copyText(caseCopyText(card), status, card));
    slackButton.addEventListener('click', () => sendSingleCase(card, status));

    head.append(heading, editButton, copyButton, slackButton);
    card.append(head, status, requestLabel, body, commentLabel);
    output.appendChild(card);
  });
}

/** Copy the current case text and flash a short confirmation. */
export async function copyText(text, status, card) {
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = translate('Текст кейса скопирован.');
  } catch {
    status.textContent = translate('Не удалось скопировать текст.');
  }
  const previous = copyStatusTimers.get(card);
  if (previous) clearTimeout(previous);
  copyStatusTimers.set(card, setTimeout(() => { status.textContent = ''; }, 4000));
}

async function sendSingleCase(card, status) {
  status.textContent = translate('Отправляем кейс в Slack...');
  try {
    const response = await fetch('/slack/send-cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        region: $('region').value,
        ...mentionPayload(),
        cases: [readCase(card)],
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Slack send failed');
    status.textContent = translate('Кейс отправлен в Slack.');
  } catch (error) {
    status.textContent = translate('Ошибка отправки в Slack: ') + error.message;
  }
}
