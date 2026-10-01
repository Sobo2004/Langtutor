// Translation system for English/Russian UI
const translations = {
  'en': {
    // Header
    'app_title': 'LangTutor',
    'subtitle_learning': 'Learning Russian',
    
    // Progress
    'level': 'Level',
    'streak': 'Streak',
    'completed': 'Completed',
    'xp': 'XP',
    'proficiency_level': 'Level',
    
    // Difficulty
    'difficulty': 'Difficulty',
    'beginner': 'Beginner',
    'intermediate': 'Inter.',
    'advanced': 'Adv.',
    
    // Quick Start
    'quick_start': 'Quick Start',
    'greetings': 'Greetings',
    'travel': 'Travel',
    'food': 'Food',
    'stop_lesson': 'Stop Lesson',
    
    // Explore
    'explore': 'Explore',
    'my_progress': 'My Progress',
    'leaderboard': 'Leaderboard',
    
    // Auth
    'logged_in_as': 'Logged in as',
    'logout': 'Logout',
    'login': 'Login',
    'signup': 'Sign Up',
    'username': 'Username',
    'email': 'Email',
    'password': 'Password',
    'create_account': 'Create your account',
    'login_to_account': 'Login to your account',
    'already_have_account': 'Already have an account?',
    'dont_have_account': "Don't have an account?",
    'admin_signin': 'Admin sign in',
    
    // Chat
    'type_message': 'Type your message...',
    'send': 'Send',
    'speak': 'Speak'
  },
  
  'ru': {
    // Header
    'app_title': 'LangTutor',
    'subtitle_learning': 'Изучаем Английский',
    
    // Progress
    'level': 'Уровень',
    'streak': 'Серия',
    'completed': 'Завершено',
    'xp': 'Опыт',
    'proficiency_level': 'Уровень',
    
    // Difficulty
    'difficulty': 'Сложность',
    'beginner': 'Начальный',
    'intermediate': 'Средний',
    'advanced': 'Продв.',
    
    // Quick Start
    'quick_start': 'Быстрый старт',
    'greetings': 'Приветствия',
    'travel': 'Путешествия',
    'food': 'Еда',
    'stop_lesson': 'Стоп урок',
    
    // Explore
    'explore': 'Обзор',
    'my_progress': 'Мой прогресс',
    'leaderboard': 'Таблица лидеров',
    
    // Auth
    'logged_in_as': 'Вы вошли как',
    'logout': 'Выйти',
    'login': 'Войти',
    'signup': 'Регистрация',
    'username': 'Имя пользователя',
    'email': 'Эл. почта',
    'password': 'Пароль',
    'create_account': 'Создайте аккаунт',
    'login_to_account': 'Войти в аккаунт',
    'already_have_account': 'Уже есть аккаунт?',
    'dont_have_account': 'Нет аккаунта?',
    'admin_signin': 'Вход администратора',
    
    // Chat
    'type_message': 'Напишите сообщение...',
    'send': 'Отправить',
    'speak': 'Говорить'
  }
};

// Get translation
function t(key, lang = null) {
  if (!lang) {
    lang = currentMode === 'ru-en' ? 'ru' : 'en';
  }
  return translations[lang][key] || key;
}

// Update all UI text based on current language mode
function updateUILanguage() {
  const lang = currentMode === 'ru-en' ? 'ru' : 'en';
  
  // Update all elements with data-i18n attribute
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const translation = translations[lang][key];
    if (translation) {
      el.textContent = translation;
    }
  });
  
  // Update placeholders
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    const translation = translations[lang][key];
    if (translation) {
      el.placeholder = translation;
    }
  });
}

// Export for use in other scripts
window.t = t;
window.updateUILanguage = updateUILanguage;
window.translations = translations;