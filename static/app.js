// Handle like and comment actions via AJAX
document.addEventListener('click', function(e){
    if(e.target.closest('.like-btn')){
        const btn = e.target.closest('.like-btn');
        const postId = btn.dataset.postId;
        const form = new FormData();
        form.append('post_id', postId);
        // optimistic UI: disable button until response
        btn.disabled = true;
        fetch('/like', {method: 'POST', body: form})
            .then(r => r.json())
            .then(data => {
                if(data.ok){
                    const count = btn.querySelector('.like-count');
                    if(count) count.textContent = data.likes;
                    // toggle visual state if server reports liked
                    if(typeof data.liked !== 'undefined'){
                        if(data.liked) btn.classList.add('liked'); else btn.classList.remove('liked');
                    }
                } else {
                    alert('按讚失敗');
                }
            }).catch(()=> alert('網路錯誤，按讚失敗'))
            .finally(()=> btn.disabled = false);
    }

    if(e.target.closest('.share-btn')){
        const btn = e.target.closest('.share-btn');
        const postId = btn.dataset.postId;
        const comment = prompt('你要附帶分享的訊息（可留空）');
        const fd = new FormData(); fd.append('original_id', postId); fd.append('message', comment || '');
        fetch('/share', {method: 'POST', body: fd})
            .then(r => r.json())
            .then(j => {
                if(j.ok){
                    alert('已分享貼文');
                    // reload page to show share
                    window.location.reload();
                } else {
                    alert('分享失敗');
                }
            }).catch(()=> alert('網路錯誤'));
    }

    if(e.target.closest('.comment-toggle')){
        const btn = e.target.closest('.comment-toggle');
        const postId = btn.dataset.postId;
        const box = document.getElementById('comments-' + postId);
        if(box.style.display === 'none') box.style.display = 'block'; else box.style.display = 'none';
    }
});

// Handle comment form submit
document.addEventListener('submit', function(e){
    if(e.target.matches('.comment-form')){
        e.preventDefault();
        const formEl = e.target;
        const postId = formEl.dataset.postId;
        const fd = new FormData(formEl);
        fd.append('post_id', postId);
        const submitBtn = formEl.querySelector('button[type="submit"]');
        if(submitBtn) submitBtn.disabled = true;
        fetch('/comment', {method: 'POST', body: fd})
            .then(r => r.json())
            .then(data => {
                if(data.ok){
                    const list = formEl.parentElement.querySelector('.comment-list');
                    const li = document.createElement('li');
                    const avatar = data.comment.avatar ? `<img src="${data.comment.avatar}" class="avatar" style="width:28px;height:28px;object-fit:cover;border-radius:50%;margin-right:8px;">` : `<div class="avatar placeholder" style="width:28px;height:28px;margin-right:8px;display:inline-flex;align-items:center;justify-content:center;">${data.comment.user[0].toUpperCase()}</div>`;
                    li.innerHTML = `${avatar}<strong>${data.comment.user}</strong>: ${data.comment.text} <span class="c-time">${data.comment.time}</span>`;
                    list.appendChild(li);
                    // clear input
                    const textInput = formEl.querySelector('input[name="text"]');
                    if(textInput) textInput.value = '';
                    // update comment count in toggle button
                    const toggle = document.querySelector('.comment-toggle[data-post-id="'+postId+'"]');
                    if(toggle){
                        const m = toggle.textContent.match(/留言 \((\d+)\)/);
                        if(m){
                            const n = parseInt(m[1]) + 1;
                            toggle.textContent = `💬 留言 (${n})`;
                        }
                    }
                } else {
                    alert(data.error || '留言失敗');
                }
            }).catch(()=> alert('網路或伺服器錯誤，留言失敗'))
            .finally(()=> { if(submitBtn) submitBtn.disabled = false; });
    }
});

// Friend search/accept handled partially in friends.html; here we can add helper if needed later

