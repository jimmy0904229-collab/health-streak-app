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

// Post menu toggle and delete handling (centralized)
document.addEventListener('click', function(e){
    // toggle three-dot menu
    const menuBtn = e.target.closest('.post-menu-btn');
    if(menuBtn){
        e.stopPropagation();
        const menu = menuBtn.parentElement && menuBtn.parentElement.querySelector('.post-menu-list');
        if(!menu) return;
        // hide other menus
        document.querySelectorAll('.post-menu-list').forEach(m=>{ if(m !== menu) m.style.display='none'; });
        menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
        return;
    }

    // delete from menu
    const delBtn = e.target.closest('.post-menu-delete-btn');
    if(delBtn){
        e.preventDefault();
        e.stopPropagation();
        if(!confirm('確定要刪除此貼文？')) return;
        const menu = delBtn.closest('.post-menu');
        const pid = menu && menu.getAttribute('data-post-id');
        if(!pid) return alert('找不到貼文 id');
        fetch(`/post/${pid}/delete`, {method:'POST', headers: {'X-Requested-With': 'XMLHttpRequest'} }).then(r=>{
            if(r.status === 200) return r.json();
            throw new Error('Network');
        }).then(j=>{ if(j.ok) location.reload(); else alert('刪除失敗') }).catch(()=> alert('刪除失敗'));
        return;
    }

    // legacy inline delete buttons
    const legacyDel = e.target.closest('.delete-post-btn');
    if(legacyDel){
        e.preventDefault();
        if(!confirm('確定要刪除此貼文？')) return;
        const pid = legacyDel.getAttribute('data-post-id');
        fetch(`/post/${pid}/delete`, {method:'POST', headers: {'X-Requested-With': 'XMLHttpRequest'} }).then(r=>r.json()).then(j=>{ if(j.ok) location.reload(); else alert('刪除失敗') }).catch(()=> alert('刪除失敗'));
        return;
    }

    // close menus when clicking outside
    if(!e.target.closest('.post-menu')){
        document.querySelectorAll('.post-menu-list').forEach(m=> m.style.display='none');
    }
});

