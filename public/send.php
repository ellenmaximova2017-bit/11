<?php
// Приём заявок с сайта: письмо на почту (+ Telegram-бот, когда будет готов).
// Заполните настройки ниже. Файл исполняется на сервере, посетители видят только результат.

const TO_EMAIL    = '';                          // куда присылать заявки, например info@aipilotmax.ru
const FROM_EMAIL  = 'noreply@aipilotmax.ru';     // адрес отправителя на вашем домене
const SITE_NAME   = 'AI Pilot Max';

// Telegram (на будущее): оставьте пустыми, пока бот не создан
const TG_BOT_TOKEN = '';                         // токен от @BotFather
const TG_CHAT_ID   = '';                         // id чата или канала, куда писать заявки

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function reply(int $code, bool $ok, string $msg = ''): void {
    http_response_code($code);
    echo json_encode(['ok' => $ok, 'message' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') reply(405, false, 'Method not allowed');
if (TO_EMAIL === '' && TG_BOT_TOKEN === '') reply(500, false, 'Приём заявок не настроен');

// Не чаще одной заявки в 30 секунд с одного IP
$ip = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
$lock = sys_get_temp_dir() . '/lead_' . md5($ip);
if (is_file($lock) && time() - filemtime($lock) < 30) reply(429, false, 'Слишком часто');

$raw = file_get_contents('php://input', false, null, 0, 20000);
$d = json_decode($raw ?: '', true);
if (!is_array($d)) reply(400, false, 'Bad request');

$clean = function ($v, int $max): string {
    $v = is_string($v) ? trim($v) : '';
    $v = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F]/u', '', $v);
    return mb_substr($v, 0, $max);
};
$name    = $clean($d['name'] ?? '', 100);
$contact = $clean($d['contact'] ?? '', 120);
$plan    = $clean($d['plan'] ?? '', 40);
$comment = $clean($d['comment'] ?? '', 2000);
$page    = $clean($d['page'] ?? '', 200);

if (mb_strlen($name) < 2 || mb_strlen($contact) < 2) reply(422, false, 'Заполните имя и контакт');

$text = "Новая заявка с сайта " . SITE_NAME . "\n\n"
      . "Имя: $name\nКонтакт: $contact\nТариф: $plan\n"
      . "Комментарий: " . ($comment !== '' ? $comment : '—') . "\n\n"
      . "Страница: $page\nIP: $ip\nВремя: " . date('d.m.Y H:i') . "\n";

$sent = false;

if (TO_EMAIL !== '') {
    $subject = '=?UTF-8?B?' . base64_encode('Заявка с сайта ' . SITE_NAME) . '?=';
    $headers = "From: " . SITE_NAME . " <" . FROM_EMAIL . ">\r\n"
             . "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n";
    $sent = mail(TO_EMAIL, $subject, $text, $headers) || $sent;
}

if (TG_BOT_TOKEN !== '' && TG_CHAT_ID !== '') {
    $ctx = stream_context_create(['http' => [
        'method'  => 'POST',
        'header'  => "Content-Type: application/x-www-form-urlencoded\r\n",
        'content' => http_build_query(['chat_id' => TG_CHAT_ID, 'text' => $text]),
        'timeout' => 5,
    ]]);
    $res = @file_get_contents('https://api.telegram.org/bot' . TG_BOT_TOKEN . '/sendMessage', false, $ctx);
    $sent = ($res !== false) || $sent;
}

if (!$sent) reply(500, false, 'Не удалось отправить');
@touch($lock);
reply(200, true, 'OK');
