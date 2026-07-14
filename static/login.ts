function toast(msg: string, err?: boolean) {
  const t = document.getElementById('toast');
  if (t) {
    t.textContent = msg; 
    t.className = 'show' + (err ? ' err' : '');
    setTimeout(() => t.className = '', 2500);
  }
}

function toggleMode(m: string) {
  const loginBox = document.getElementById('loginBox');
  const regBox = document.getElementById('regBox');
  if (loginBox) loginBox.classList.toggle('hidden', m !== 'login');
  if (regBox) regBox.classList.toggle('hidden', m !== 'reg');
}

(window as any).toggleMode = toggleMode;

const btnLogin = document.getElementById('btnLogin');
if (btnLogin) {
  btnLogin.onclick = async () => {
    const lUser = document.getElementById('lUser') as HTMLInputElement;
    const lPass = document.getElementById('lPass') as HTMLInputElement;
    const username = lUser?.value.trim();
    const password = lPass?.value;
    
    if(!username || !password) return toast('Заполните все поля', true);
    
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username, password})
      });
      const d = await r.json();
      if(r.ok) location.href = '/';
      else toast(d.error, true);
    } catch(e) { 
      toast('Ошибка', true); 
    }
  };
}

const btnSendCode = document.getElementById('btnSendCode') as HTMLButtonElement;
if (btnSendCode) {
  btnSendCode.onclick = async () => {
    const rEmail = document.getElementById('rEmail') as HTMLInputElement;
    const email = rEmail?.value.trim();
    
    if(!email) return toast('Введите email', true);
    
    btnSendCode.disabled = true;
    btnSendCode.textContent = 'Отправка...';
    
    try {
      const r = await fetch('/api/auth/send-code', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email})
      });
      const d = await r.json();
      if(r.ok) {
        toast('Код отправлен!');
        const step1 = document.getElementById('step1');
        const step2 = document.getElementById('step2');
        if (step1) step1.classList.add('hidden');
        if (step2) step2.classList.remove('hidden');
      } else {
        toast(d.error, true);
      }
    } catch(e) { 
      toast('Ошибка связи', true); 
    }
    
    btnSendCode.disabled = false;
    btnSendCode.textContent = 'Отправить код';
  };
}

const btnReg = document.getElementById('btnReg');
if (btnReg) {
  btnReg.onclick = async () => {
    const rEmail = document.getElementById('rEmail') as HTMLInputElement;
    const rCode = document.getElementById('rCode') as HTMLInputElement;
    const rUser = document.getElementById('rUser') as HTMLInputElement;
    
    const email = rEmail?.value.trim();
    const code = rCode?.value.trim();
    const username = rUser?.value.trim();
    
    if(!code || !username) return toast('Заполните код и логин', true);
    
    try {
      const r = await fetch('/api/auth/register', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, code, username})
      });
      const d = await r.json();
      if(r.ok) {
        alert('Регистрация успешна! Ваш временный пароль: 1');
        location.href = '/';
      } else {
        toast(d.error, true);
      }
    } catch(e) { 
      toast('Ошибка связи', true); 
    }
  };
}
