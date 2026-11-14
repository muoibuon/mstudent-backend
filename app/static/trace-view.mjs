const ROUTES = {
  stop: 'Dừng sau lọc nhiễu',
  direct: 'Đi thẳng tới trích việc',
  review: 'LLM xem lại',
  fallback: 'LLM dự phòng',
};

export function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return 'Chưa có thời gian';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString('vi-VN', {maximumFractionDigits: 2})} giây`;
}

export function traceSummary(trace) {
  const steps = Array.isArray(trace.steps) ? trace.steps : [];
  const decisions = steps.filter((s) => s.agent === 'Decision');
  const mains = steps.filter((s) => s.kind === 'llm' && s.agent !== 'Decision');
  const decision = decisions.findLast((s) => !s.error && ['stop', 'direct', 'review'].includes(s.output?.route));
  const main = mains.some((s) => !s.error);
  const route = decisions.at(-1)?.output?.route || steps.find((s) => s.agent === 'Routing')?.output?.route;
  const rules = steps.some((s) => s.kind === 'rules' && ['Triage', 'Extractor'].includes(s.agent));
  let key = 'unknown', label = 'Chưa đủ dữ liệu', description = 'Trace chưa ghi đủ bước để xác định cách xử lý.';
  if (trace.mode === 'cache') {
    key = 'cache'; label = 'Kết quả đã lưu'; description = 'Dùng lại kết quả, không ghi nhận lượt xử lý mới.';
  } else if (trace.mode === 'offline' || rules) {
    key = 'rules'; label = decisions.length || mains.length ? 'Bộ luật dự phòng' : 'Bộ luật';
    description = decisions.length || mains.length ? 'AI đã được thử; kết quả cuối do bộ luật xử lý.' : 'Kết quả do bộ luật xử lý, không ghi nhận bước gọi model.';
  } else if (decision && main) {
    key = 'hybrid'; label = 'Decision + LLM'; description = 'Decision lọc và phân loại; LLM chính xử lý nội dung được giữ lại.';
  } else if (decision && route === 'stop') {
    key = 'decision'; label = 'Chỉ Decision'; description = 'Tin được dừng sau bước lọc nhiễu; không ghi nhận bước gọi LLM chính.';
  } else if (main && decisions.length) {
    key = 'fallback'; label = 'Decision lỗi → LLM'; description = 'Decision không trả quyết định dùng được; LLM chính xử lý dự phòng.';
  } else if (main && steps.some((s) => s.agent === 'Routing')) {
    key = 'main'; label = 'Chỉ LLM'; description = 'Gate Decision tắt hoặc chưa cấu hình; LLM chính lọc và trích việc.';
  } else if (main) {
    key = 'legacy'; label = 'AI · trace cũ'; description = 'Có bước LLM nhưng trace không ghi riêng Decision; chưa thể kết luận có kết hợp hay không.';
  }
  const timings = steps.map((s) => s.ms).filter((ms) => Number.isFinite(ms) && ms >= 0);
  return {
    key, label, description, route,
    routeLabel: key === 'rules' ? 'Kết quả cuối bằng bộ luật' : ROUTES[route] || 'Không có tuyến được ghi nhận',
    decision: decision?.output || null,
    decisionSteps: decisions.length,
    mainSteps: mains.length,
    totalMs: timings.length ? timings.reduce((a, b) => a + b, 0) : null,
    failedSteps: steps.filter((s) => s.error).length,
  };
}

export function stepDescription(step, categories) {
  if (step.error) return 'Bước này không hoàn tất; xem lỗi kỹ thuật bên dưới.';
  const out = step.output || {};
  if (step.agent === 'Decision') {
    const probability = Number.isFinite(out.relevant) ? `Độ liên quan ${(out.relevant * 100).toFixed(1)}%. ` : '';
    const category = categories[out.category] ? `Phân loại sơ bộ: ${categories[out.category]}. ` : '';
    return probability + category + (ROUTES[out.route] || 'Đã ghi nhận quyết định.');
  }
  if (step.agent === 'Extractor' || step.agent === 'Review') {
    const count = Array.isArray(out.tasks) ? out.tasks.length : null;
    return (step.agent === 'Review' ? 'Xem lại độ liên quan và phân loại, rồi trích việc trong cùng một lượt. ' : 'Đọc nội dung và trích việc, hạn, môn và địa điểm. ') + (count === null ? '' : `Trích được ${count} việc.`);
  }
  if (step.agent === 'Planner') return `Tạo ${out.created?.length || 0} việc, cập nhật ${out.updated?.length || 0} việc bằng Python.`;
  if (step.agent === 'Triage') return out.relevant === false ? 'Kết luận thông báo không liên quan.' : 'Đánh giá độ liên quan của thông báo.';
  if (step.agent === 'Documents') return 'Đọc tài liệu riêng với email; xem kết quả hoặc lỗi trong dữ liệu kỹ thuật.';
  if (step.agent === 'Routing') return 'Chọn tuyến dự phòng vì Decision tắt hoặc chưa cấu hình.';
  return step.kind === 'rules' ? 'Xử lý bằng bộ luật.' : 'Kết quả của bước đã được ghi nhận.';
}
