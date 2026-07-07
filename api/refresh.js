export default async function handler(request, response) {
  if (request.method !== "POST") {
    response.setHeader("Allow", "POST");
    return response.status(405).json({ ok: false, error: "只支持 POST 请求" });
  }

  const token = process.env.GITHUB_TRIGGER_TOKEN;
  const owner = process.env.GITHUB_OWNER;
  const repo = process.env.GITHUB_REPO;
  const workflow = process.env.GITHUB_WORKFLOW_FILE || "refresh-bank-data.yml";
  const ref = process.env.GITHUB_REF || "main";

  if (!token || !owner || !repo) {
    return response.status(500).json({
      ok: false,
      error: "Vercel 环境变量未配置完整：GITHUB_TRIGGER_TOKEN / GITHUB_OWNER / GITHUB_REPO"
    });
  }

  try {
    const githubResponse = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
          "User-Agent": "a-bank-monitor"
        },
        body: JSON.stringify({
          ref,
          inputs: {
            source: "manual"
          }
        })
      }
    );

    if (!githubResponse.ok) {
      const body = await githubResponse.text();
      return response.status(githubResponse.status).json({
        ok: false,
        error: `GitHub Actions 触发失败：${githubResponse.status} ${body}`
      });
    }

    return response.status(202).json({
      ok: true,
      message: "刷新任务已提交，稍后页面会自动读取最新结果。"
    });
  } catch (error) {
    return response.status(500).json({
      ok: false,
      error: `刷新触发异常：${error.message || error}`
    });
  }
}
