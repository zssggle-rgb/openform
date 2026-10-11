import { useState } from "react";

export interface QuestionDisplay {
  id: string; title: string; kind: string; data_path: string; has_standard: boolean;
  expected: unknown; choices: unknown[]; field_labels: Record<string, string>;
  answer_schema: AnswerSchema;
}
interface AnswerSchema { title?: string; properties?: Record<string, AnswerSchema>; items?: AnswerSchema }

export function answerAt(data: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined, data);
}

function Value({ value, labels = {}, schema = {} }: { value: unknown; labels?: Record<string, string>; schema?: AnswerSchema }) {
  if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return <span className="field-help">未填写</span>;
  if (Array.isArray(value)) return <ol className="answer-values">{value.map((item, index) => <li key={index}><Value value={item} labels={labels} schema={schema.items} /></li>)}</ol>;
  if (typeof value === "object") return <dl className="answer-fields">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{schema.properties?.[key]?.title ?? labels[key] ?? key}</dt><dd><Value value={item} schema={schema.properties?.[key]} /></dd></div>)}</dl>;
  return <span>{String(value)}</span>;
}

function AnswerImage({ url, title }: { url: string; title: string }) {
  const [failed, setFailed] = useState(false);
  return failed ? <p className="error-box">照片暂时无法打开，请稍后重新查看。</p> : <a href={url} target="_blank" rel="noreferrer"><img className="evidence-image" src={url} alt={title} onError={() => setFailed(true)} /></a>;
}

export function AnswerDisplay({ question, data, fileBase }: { question: QuestionDisplay; data: unknown; fileBase: string }) {
  const answer = answerAt(data, question.data_path);
  const files = Array.isArray(answer) ? answer.filter((item): item is string => typeof item === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(item)) : [];
  return <div className="answer-question"><h3>{question.title}</h3><div className="answer-data">{question.kind === "image" ? files.length ? files.map((file) => <AnswerImage key={`${fileBase}/${file}`} url={`${fileBase}/${file}`} title={question.title} />) : <span className="field-help">未添加照片</span> : <Value value={answer} labels={question.field_labels} schema={question.answer_schema} />}</div>
    {question.has_standard && <div className="answer-standard">参考答案：<Value value={question.expected} labels={question.field_labels} schema={question.answer_schema} /></div>}
  </div>;
}
