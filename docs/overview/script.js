(()=>{
  const viewer=document.querySelector('#viewer'),image=document.querySelector('#viewer-img'),title=document.querySelector('#viewer-title'),canvas=document.querySelector('.viewer-body');
  const close=document.querySelector('#close-viewer'),size=document.querySelector('#size-viewer');
  let trigger=null;
  document.querySelectorAll('a[data-shot]').forEach(link=>link.addEventListener('click',event=>{
    if(typeof viewer.showModal!=='function')return;
    event.preventDefault();trigger=link;const source=link.querySelector('img');
    image.src=source.currentSrc||source.src;image.alt=source.alt;title.textContent=link.dataset.shot==='studio'?'Studio 字幕与视频编辑':'识别方案';
    canvas.classList.remove('actual');size.textContent='原尺寸';viewer.showModal();document.body.classList.add('viewing');close.focus();
  }));
  size.addEventListener('click',()=>{const actual=canvas.classList.toggle('actual');size.textContent=actual?'适应窗口':'原尺寸';});
  close.addEventListener('click',()=>viewer.close());
  viewer.addEventListener('click',event=>{if(event.target===viewer){const r=viewer.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)viewer.close();}});
  viewer.addEventListener('close',()=>{document.body.classList.remove('viewing');trigger?.focus();});
})();
