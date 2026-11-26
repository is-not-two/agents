export interface Topic {attachment_status?:{filename:string;scan_state:"pending"|"clean"|"rejected"}[];id:string;title:string;score:number;body?:string;excerpt?:string;version:number;state?:string;author_feedback?:string;review?:{score:number;rationale:string;reviewed_at:string}|null;files?:{id:string;filename:string;bytes:number}[]}
export interface Evidence {post_id:string;version:number;quote:string;title:string}
export interface Answer {mode:string;reason?:string;reason_code?:string;evidence:Evidence[]}
export class CommunityError extends Error {constructor(public status:number,message:string){super(message)}}
export async function api<T>(path:string,method="GET",data?:unknown):Promise<T>{
 const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),path==="ask"?35000:12000);
 try {
  const r=await fetch("/api/community/"+path,{method,credentials:"same-origin",cache:"no-store",signal:controller.signal,headers:data?{"Content-Type":"application/json"}:{},body:data?JSON.stringify(data):undefined});
  if(r.status===429){
   const raw=r.headers.get("Retry-After");
   if(raw && /^[1-9][0-9]{0,4}$/.test(raw))throw new CommunityError(429,`请求过于频繁，请在 ${Number(raw)} 秒后重试。`);
  }
  if(!r.ok)throw new CommunityError(r.status,({401:"请先登录交流区，输入内容会保留。",403:"当前身份没有此操作权限。",404:"内容不存在，或已被撤回。",409:"内容已变化，请刷新后再操作。",422:"请检查必填项、字数和分数范围。",429:"操作频繁，请稍后再试。"} as Record<number,string>)[r.status]||"暂时无法完成请求，请重试。");
  return r.status===204?{} as T:await r.json();
 }catch(e){if(e instanceof CommunityError)throw e;throw new Error("连接失败或等待超时，输入内容已保留，请重试。")}
 finally {clearTimeout(timer)}
}
export function keywords(question:string,manual:string):string[]{
 if(manual.trim()){const items=[...new Set(manual.split(/[,，、]/).map(x=>x.trim()).filter(Boolean))];if(!items.length||items.length>5||items.some(x=>Array.from(x).length>40))throw Error("请填写1到5个关键词，每个最多40字。");return items}
 const ignore=new Set("如何 怎么 怎样 可以 请问 帮我 我想 进行 一个 什么 哪些 有没有 能不能 是否 使用 办法 方法 需要".split(" "));
 const Segmenter=(Intl as any).Segmenter;
 for(const filler of "今天 遇到 问题 请教 一下 大家 类似 经验 帮忙 看一下 想问 我要 出来 想要 请教一下".split(" "))ignore.add(filler);
 const words=Segmenter?[...new Segmenter("zh",{granularity:"word"}).segment(question)].filter(x=>x.isWordLike).map(x=>x.segment as string):question.match(/[\p{L}\p{N}]+/gu)||[];
 const result=[...new Set([...(question.match(/豆包|飞书|钉钉/gu)||[]),...words].filter(x=>x.length>1&&x.length<=40&&!ignore.has(x)))].slice(0,5);
 if(result.length)return result;
 const first=question.match(/[\p{L}\p{N}]{1,40}/u);if(first)return [first[0]];
 throw Error("请描述想解决的工作问题。");
}

