"use client";

// 隐私说明 (/privacy): what is collected, what is sent to whom, how long it is kept and what the author can do. Open to everyone,
// signed in or not. The words are the ones the author of the product approved (the 2026-10-15 draft); the date at the top is
// the day they were last changed.
import { Button } from "../ui";

export const PRIVACY_UPDATED = "2026 年 10 月 15 日";
export const PRIVACY_CONTACT = "zcy4711@gmail.com";
const DEEPSEEK_POLICY = "https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html";

export function PrivacyPage({ go, signedIn }: { go: (href: string) => void; signedIn: boolean }) {
  return (
    <article className="page article privacy" aria-labelledby="privacy-title">
      <p className="article-back"><Button kind="text" onClick={() => go(signedIn ? "/" : "/login")}>{signedIn ? "回到首页" : "回到登录"}</Button></p>
      <h1 id="privacy-title">隐私说明</h1>
      <p className="label article-date">最近更新：{PRIVACY_UPDATED}</p>
      <p>Story Continuity 是给小说作者用的连续性检查和写作助手。这页说明我们收集什么、怎么用、交给谁处理、保存多久，以及你可以怎么做。</p>

      <h2>我们收集什么</h2>
      <ul>
        <li><strong>账号信息</strong>：登录账号、密码（只保存加密后的结果，任何人都看不到原文）、显示名称、头像选择。</li>
        <li><strong>恢复邮箱</strong>（可选）：只用来找回密码和发送必要的安全通知。</li>
        <li><strong>你的作品</strong>：章节正文、草稿、你确认的事实、计划和伏笔记录，以及检查结果和助手的对话。</li>
        <li><strong>用量记录</strong>：每次检查和助手任务用了多少字，用来计算每天的额度。</li>
        <li><strong>反馈</strong>：你对助手回答点的「有用 / 没用」和原因，不包含回答内容。</li>
      </ul>
      <p>我们不收集你的真实姓名、手机号、位置，也不使用任何第三方广告或统计追踪。网站只使用保持登录所需的 Cookie。</p>

      <h2>怎么用</h2>
      <p>只用来提供这个服务本身：保存你的作品、做连续性检查、运行写作助手、计算额度、找回密码。</p>
      <p>我们不会公开、出售你的作品，也不会用你的作品训练任何模型。</p>

      <h2>交给谁处理</h2>
      <ul>
        <li><strong>服务器</strong>：网站和数据存放在新加坡的腾讯云服务器上。</li>
        <li><strong>DeepSeek</strong>：做连续性检查和运行写作助手时，我们会把处理所需的文字片段（相关的章节或段落、你的问题）发给 DeepSeek（杭州深度求索人工智能基础技术研究有限公司）的模型接口，由它返回结果。这些片段会被发送到 DeepSeek 在中国大陆的服务器上处理。我们只发这一次请求需要的内容，不发你的账号信息。DeepSeek 如何保存和使用这些数据，以它的<a href={DEEPSEEK_POLICY} target="_blank" rel="noopener noreferrer">隐私政策</a>为准。</li>
      </ul>
      <p>除此之外，我们不会把你的数据交给任何人，法律要求的情况除外。</p>

      <h2>保存多久</h2>
      <ul>
        <li><strong>作品和对话</strong>：一直保存，直到你删除。删除作品会同时删除它的章节、草稿、检查结果和助手对话。</li>
        <li><strong>访客空间</strong>：到期后连同其中的作品一起删除。</li>
        <li><strong>运行日志</strong>：只记录请求是否成功、耗时这类信息，不记录作品正文，保留 30 天。</li>
        <li><strong>账号</strong>：目前还不能在页面上自行删除账号。如需删除账号及全部数据，请发邮件联系我们，我们会在 7 天内处理完毕并回复你。</li>
      </ul>

      <h2>你可以做什么</h2>
      <ul>
        <li>随时在作品里修改或删除你的内容。</li>
        <li>发邮件要求我们导出、更正或删除你的数据，我们会在 7 天内处理。</li>
      </ul>

      <h2>关于 AI 生成的内容</h2>
      <p>检查结果和助手的回答由 AI 生成，可能有错漏，仅供参考。助手的每句话都附有出处，请点开核对。助手只提建议，不会自己改动你的正文；你采用的改法会成为你自己的文字。</p>

      <h2>联系我们</h2>
      <p>对这份说明或你的数据有任何问题、投诉或要求，请发邮件到 <a href={`mailto:${PRIVACY_CONTACT}`}>{PRIVACY_CONTACT}</a>。</p>

      <h2>这份说明的变更</h2>
      <p>内容有变化时，我们会更新本页顶部的日期；重要的变化会在网站上提示。</p>
    </article>
  );
}
