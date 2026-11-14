import assert from 'node:assert/strict';
import test from 'node:test';
import {traceSummary, formatDuration, stepDescription} from '../app/static/trace-view.mjs';

const decision = (route = 'direct') => ({agent:'Decision', kind:'llm', ms:746.7, output:{route, relevant:0.9628, category:'class_change', category_conf:0.9}});
const extractor = {agent:'Extractor', kind:'llm', ms:3424.1, output:{tasks:[{category:'class_change'}]}};
const planner = {agent:'Planner', kind:'python', ms:14, output:{created:[{id:1}], updated:[]}};
const trace = (...steps) => ({mode:'llm', steps});

test('actual combined trace gets a clear label, counts and timing', () => {
  const info = traceSummary(trace(decision(), extractor, planner));
  assert.equal(info.key, 'hybrid');
  assert.equal(info.label, 'Decision + LLM');
  assert.equal(info.routeLabel, 'Đi thẳng tới trích việc');
  assert.equal(info.decisionSteps, 1);
  assert.equal(info.mainSteps, 1);
  assert.equal(Math.round(info.totalMs), 4185);
});

test('noise stops at Decision without claiming main LLM ran', () => {
  const info = traceSummary(trace(decision('stop')));
  assert.equal(info.label, 'Chỉ Decision');
  assert.equal(info.mainSteps, 0);
});

test('review is still combined when main reviews in one step', () => {
  const info = traceSummary(trace(decision('review'), {...extractor, agent:'Review'}));
  assert.equal(info.key, 'hybrid');
  assert.equal(info.routeLabel, 'LLM xem lại');
});

test('failed Decision followed by main is marked as fallback', () => {
  const info = traceSummary(trace({...decision('fallback'), error:'ReadTimeout'}, extractor));
  assert.equal(info.label, 'Decision lỗi → LLM');
  assert.equal(info.failedSteps, 1);
  assert.equal(info.key, 'fallback');
});

test('gate disabled is distinguishable from a failed Decision', () => {
  const info = traceSummary(trace({agent:'Routing', kind:'python', output:{route:'fallback'}}, extractor));
  assert.equal(info.label, 'Chỉ LLM');
  assert.equal(info.decisionSteps, 0);
});

test('offline result takes precedence over attempted AI', () => {
  const info = traceSummary({mode:'offline', steps:[decision(), {...extractor, error:'TimeoutError'}, {agent:'Extractor', kind:'rules', output:{tasks:[]}}]});
  assert.equal(info.label, 'Bộ luật dự phòng');
  assert.equal(info.key, 'rules');
  assert.equal(info.failedSteps, 1);
});

test('plain rules mode does not claim an AI call', () => {
  const info = traceSummary({mode:'offline', steps:[{agent:'Triage', kind:'rules'}]});
  assert.equal(info.label, 'Bộ luật');
  assert.equal(info.mainSteps, 0);
});

test('rules used only for event enrichment do not relabel the main result', () => {
  const info = traceSummary(trace(decision(), extractor, {agent:'EventDetails', kind:'rules'}));
  assert.equal(info.key, 'hybrid');
});

test('old traces without a separate Decision step remain explicit about uncertainty', () => {
  const info = traceSummary(trace({agent:'Triage', kind:'llm'}, extractor));
  assert.equal(info.key, 'legacy');
  assert.match(info.description, /chưa thể kết luận/);
});

test('technical-only and missing data do not invent a model path or timing', () => {
  const info = traceSummary({mode:'llm', steps:[{agent:'Documents', kind:'python'}]});
  assert.equal(info.key, 'unknown');
  assert.equal(info.totalMs, null);
  assert.equal(traceSummary({mode:'llm'}).key, 'unknown');
});

test('cache is named independently', () => {
  assert.equal(traceSummary({mode:'cache', steps:[]}).label, 'Kết quả đã lưu');
});

test('invalid and absent times are not presented as a measured zero', () => {
  assert.equal(formatDuration(undefined), 'Chưa có thời gian');
  assert.equal(formatDuration(NaN), 'Chưa có thời gian');
  assert.equal(formatDuration(-1), 'Chưa có thời gian');
  assert.equal(formatDuration(0), '0 ms');
  assert.equal(formatDuration(3424.1), '3,42 giây');
});

test('human explanations expose the route and real category', () => {
  const explanation = stepDescription(decision(), {class_change:'Đổi lịch'});
  assert.match(explanation, /96\.3%/);
  assert.match(explanation, /Đổi lịch/);
  assert.match(explanation, /Đi thẳng/);
  assert.match(stepDescription(extractor, {}), /1 việc/);
  assert.match(stepDescription({...extractor, error:'Error'}, {}), /không hoàn tất/);
  assert.match(stepDescription({agent:'TimeDefaults', output:{due_at:'2026-11-16T08:00:00+07:00'}}, {}), /08:00.*13:00.*19:00/);
});
