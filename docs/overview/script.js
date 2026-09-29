(()=>{
  const dialog=document.querySelector('#viewer'),picture=document.querySelector('#viewer-image'),title=document.querySelector('#viewer-title');
  const canvas=document.querySelector('.viewer-canvas'),toggle=document.querySelector('#toggle-original'),size=document.querySelector('#toggle-size'),download=document.querySelector('#download-image');
  let trigger=null,annotated='',original='',plain=false;
  function showPicture(){picture.src=plain?original:annotated;download.href=picture.src;toggle.textContent=plain?'看标注图':'看无标注图';picture.alt=title.textContent+(plain?'（无标注图）':'（导视标注图）');if(canvas.classList.contains('actual'))picture.style.width=plain?'2048px':'2144px';}
  document.querySelectorAll('a.zoom').forEach(link=>link.addEventListener('click',event=>{
    if(!dialog.showModal)return;
    event.preventDefault();trigger=link;annotated=link.getAttribute('href');original=link.dataset.original;plain=false;
    title.textContent=link.dataset.title;canvas.classList.remove('actual');size.textContent='原尺寸';showPicture();dialog.showModal();document.body.classList.add('viewing');document.querySelector('#close-viewer').focus();
  }));
  toggle.addEventListener('click',()=>{plain=!plain;showPicture()});
  size.addEventListener('click',()=>{const actual=canvas.classList.toggle('actual');size.textContent=actual?'适应窗口':'原尺寸';if(actual)picture.style.width=plain?'2048px':'2144px';else picture.style.width='';});
  document.querySelector('#close-viewer').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  dialog.addEventListener('close',()=>{document.body.classList.remove('viewing');picture.style.width='';trigger?.focus();});
})();
