// Handle like and comment actions via AJAX
document.addEventListener('click', function(e){
    if(e.target.closest('.like-btn')){
        const btn = e.target.closest('.like-btn');
        const postId = btn.dataset.postId;
        const form = new FormData();
        form.append('post_id', postId);
        fetch('/like', {method: 'POST', body: form})
            .then(r => r.json())
            .then(data => {
                if(data.ok){
                    const count = btn.querySelector('.like-count');
                    if(count) count.textContent = data.likes;
                }
            });
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
        fetch('/comment', {method: 'POST', body: fd})
            .then(r => r.json())
            .then(data => {
                if(data.ok){
                    const list = formEl.parentElement.querySelector('.comment-list');
                    const li = document.createElement('li');
                    li.innerHTML = `<strong>${data.comment.user}</strong>: ${data.comment.text} <span class="c-time">${data.comment.time}</span>`;
                    list.appendChild(li);
                    // clear input
                    formEl.querySelector('input[name="text"]').value = '';
                    // update comment count in toggle button
                    const toggle = document.querySelector('.comment-toggle[data-post-id="'+postId+'"]');
                    if(toggle){
                        const match = toggle.textContent.match(/留言 \((\d+)\)/);
                        if(match){
                            const n = parseInt(match[1]) + 1;
                            toggle.textContent = `💬 留言 (${n})`;
                        }
                    }
                } else {
                    alert('留言失敗');
                }
            }).catch(()=> alert('留言錯誤'));
    }
});
