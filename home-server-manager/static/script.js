let currentPath = '';

function showSection(section) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById(`${section}-section`).classList.add('active');
    
    if (section === 'files') {
        loadFiles();
    } else if (section === 'system') {
        loadSystemInfo();
        setInterval(loadSystemInfo, 5000);
    }
}

async function loadFiles(path = null) {
    if (path) currentPath = path;
    
    try {
        const response = await fetch(`/api/files?path=${encodeURIComponent(currentPath)}`);
        const data = await response.json();
        
        if (response.ok) {
            currentPath = data.current_path;
            document.getElementById('current-path').textContent = currentPath;
            window.parentPath = data.parent_path;
            renderFileList(data.items);
        } else {
            alert('Ошибка загрузки файлов: ' + data.error);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Ошибка соединения с сервером');
    }
}

function renderFileList(items) {
    const container = document.getElementById('file-list');
    container.innerHTML = '';
    
    items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'file-item';
        
        const size = item.type === 'file' ? formatBytes(item.size) : '<DIR>';
        
        div.innerHTML = `
            <div class="file-name ${item.type}" onclick="navigateTo('${item.path}')">
                ${item.type === 'directory' ? '📁 ' : '📄 '}${item.name}
            </div>
            <div class="file-size">${size}</div>
            <div class="file-actions">
                ${item.type === 'file' ? `<button class="download-btn" onclick="downloadFile('${item.path}')">Скачать</button>` : ''}
                <button class="delete-btn" onclick="deleteItem('${item.path}')">Удалить</button>
            </div>
        `;
        
        container.appendChild(div);
    });
}

function navigateTo(path) {
    loadFiles(path);
}

function goUp() {
    if (window.parentPath) {
        loadFiles(window.parentPath);
    }
}

async function createFolder() {
    const folderName = document.getElementById('new-folder-name').value;
    if (!folderName) {
        alert('Введите имя папки');
        return;
    }
    
    try {
        const response = await fetch('/api/mkdir', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: currentPath, dirname: folderName})
        });
        
        const data = await response.json();
        if (response.ok) {
            document.getElementById('new-folder-name').value = '';
            loadFiles();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Ошибка соединения с сервером');
    }
}

async function uploadFile() {
    const fileInput = document.getElementById('file-upload');
    const file = fileInput.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('path', currentPath);
    
    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        if (response.ok) {
            alert('Файл загружен успешно');
            loadFiles();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Ошибка соединения с сервером');
    }
    
    fileInput.value = '';
}

async function downloadFile(filePath) {
    window.location.href = `/api/download?path=${encodeURIComponent(filePath)}`;
}

async function deleteItem(itemPath) {
    if (!confirm('Удалить этот элемент?')) return;
    
    try {
        const response = await fetch('/api/delete', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: itemPath})
        });
        
        const data = await response.json();
        if (response.ok) {
            loadFiles();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Ошибка соединения с сервером');
    }
}

async function loadSystemInfo() {
    try {
        const response = await fetch('/api/system');
        const data = await response.json();
        
        if (response.ok) {
            // CPU
            document.getElementById('cpu-info').innerHTML = `
                <p>Загрузка: ${data.cpu.percent}%</p>
                <p>Ядер: ${data.cpu.count}</p>
            `;
            document.getElementById('cpu-progress').style.width = `${data.cpu.percent}%`;
            
            // RAM
            document.getElementById('ram-info').innerHTML = `
                <p>Использовано: ${formatBytes(data.memory.used)} / ${formatBytes(data.memory.total)}</p>
                <p>Загрузка: ${data.memory.percent}%</p>
            `;
            document.getElementById('ram-progress').style.width = `${data.memory.percent}%`;
            
            // Disk
            document.getElementById('disk-info').innerHTML = `
                <p>Использовано: ${formatBytes(data.disk.used)} / ${formatBytes(data.disk.total)}</p>
                <p>Свободно: ${formatBytes(data.disk.free)}</p>
            `;
            document.getElementById('disk-progress').style.width = `${data.disk.percent}%`;
            
            // System info
            document.getElementById('system-info').innerHTML = `
                <p><strong>Хост:</strong> ${data.system.hostname}</p>
                <p><strong>ОС:</strong> ${data.system.os}</p>
                <p><strong>Python:</strong> ${data.system.python_version}</p>
                <p><strong>Обновлено:</strong> ${new Date(data.timestamp).toLocaleTimeString()}</p>
            `;
        }
    } catch (error) {
        console.error('Error loading system info:', error);
    }
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Инициализация
showSection('files');