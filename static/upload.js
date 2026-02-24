const chunkSize = 1024 * 512;

async function uploadWithResume(file) {
  const status = document.getElementById('status');
  let uploaded = Number(localStorage.getItem(`upload:${file.name}`) || 0);
  if (uploaded > file.size) uploaded = 0;

  while (uploaded < file.size) {
    const end = Math.min(uploaded + chunkSize, file.size);
    const blob = file.slice(uploaded, end);
    const formData = new FormData();
    formData.append('file', blob, file.name);
    formData.append('filename', file.name);

    const resp = await fetch('/upload', {
      method: 'POST',
      headers: { 'Content-Range': `bytes ${uploaded}-${end - 1}/${file.size}` },
      body: formData,
    });

    if (!resp.ok) {
      status.textContent = `上传失败：${await resp.text()}`;
      return;
    }

    uploaded = end;
    localStorage.setItem(`upload:${file.name}`, String(uploaded));
    status.textContent = `上传中：${((uploaded / file.size) * 100).toFixed(1)}%`;
  }

  localStorage.removeItem(`upload:${file.name}`);
  status.textContent = '上传完成';
  window.location.reload();
}

document.getElementById('uploadBtn')?.addEventListener('click', () => {
  const file = document.getElementById('fileInput').files[0];
  if (!file) return;
  uploadWithResume(file);
});
