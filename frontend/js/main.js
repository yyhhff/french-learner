// Wave 0 入口：装配所有模块，发布函数到 window（保 inline onclick），执行顶层副作用。
import { apiRequest } from './api.js';
import { a1PathDone, a1PathFinish, a1PathGo, a1PathNext, closeA1Path, openA1Path } from './views/a1-path.js';
import { FALLBACK_PROFILE, FALLBACK_SCENES, buildFallbackCards, capitalize, esc, fmtNum, normalizeTurn, notify, setMicStatus, state, userTurn } from './store.js';
import { answerAssessment, goAssessmentRecommend, initAssessment, jumpAssessmentLevel, nextAssessment, prevAssessment, renderAssessmentQuestion, renderAssessmentResult, showAssessmentPane, startAssessment, submitAssessment } from './views/assessment.js';
import { browserRecognizeFallback, buildAsrContext, buildAsrHints, checkAsr, fallbackSpeak, pickMimeType, playCurrentAudio, speak, toggleMic, transcribeAudio, unlockAudio } from './views/audio.js';
import { applyChatResult, chatLinkBtnHTML, cleanToken, detailFromFallback, detectLinkingPairs, fallbackChat, messageHTML, renderChat, renderHeader, renderLedger, renderScenes, renderTop, renderTries, renderVocab, resetChat, sceneCards, selectScene, sendTyped, sentenceTokensHTML, submitUserText, translateTurns, tryIt, wordTokensHTML } from './views/chat.js';
import { answerExamChoice, backExamToPapers, examAnswerDone, examTypeName, initExam, nextExam, onExamTextInput, openExamPaper, prevExam, renderExamPapers, renderExamQuestion, renderExamResult, saveExamCurrentText, showExamPane, submitExam, toggleExamRecord, transcribeExamAudio } from './views/exam.js';
import { closeFeedback, openFeedback, selectFbCat, submitFeedback } from './views/feedback.js';
import { achievementCardHTML, dailyGoalsCardHTML, microProgressCardHTML, renderGrowth, renderRoadmap, skillCardHTML, switchView } from './views/growth.js';
import { listenBack, listenFinish, listenOpen, listenPickLevel, listenPlay, listenPlayAll, listenSetSpeed, listenSetVariant, listenSubmit, listenToggleDictation, listenToggleLoop, switchListenView } from './views/listen.js';
import { closeOnboarding, closeRetention, goOnboardingTarget, maybeShowOnboarding, maybeShowRetention, onboardingSeen, reopenOnboarding, retentionContinue, showOnboardingStep } from './views/onboarding.js';
import { applyPronProgressItem, buildPronIndex, closePronBook, closePronCard, dismissPronTip, findRulesForCard, loadPronData, loadPronDetails, loadPronProgress, loadPronSummaries, maybeShowPronTip, normIpa, openPronBook, openPronCard, openPronCardForNoRule, postPronProgress, pronBadgeHTML, pronFocusLabel, pronKey, pronLearnedTotal, pronProgressHTML, pronStageOf, pronTotalRules, renderPronBook, renderPronCard, switchPronCard, updatePronBookEntry, updatePronCardProgressUI } from './views/pron.js';
import { applyCollectResult, collectAllWords, collectReadWord, gentleReadNote, loadReadLevels, markReadComplete, openReadText, postCollect, recommendNext, renderReadLevels, renderReadLines, renderReadTexts, renderReadWords, selectReadLevel, setOffline, showReadDetail } from './views/reading.js';
import { closeReview, doReview, openReview, readOfflineNote, renderReviewCard, updateReadVocabBadge } from './views/review.js';
import { ipaEq, levDistance, pronShadowReset, pronShadowSection, scoreShadow, shadowFeedback, shadowSelfAssess, stringSim, toggleShadowRecord, transcribeShadowAudio } from './views/shadow.js';
import { closePronPopover, openFullFromPop, openWordPopover, pronPopOutside, toggleLinkingInline } from './views/word-popover.js';
import { initPronCoach, nextPronCoachSentence, setPronCoachFocus, switchPronCoachView, togglePronCoachRecord } from './views/pron_coach.js';
import { goTodayTask, initToday } from './views/today.js';

async function init(){
  document.addEventListener('keydown', e=>{
    if(e.key!=='Escape') return;
    closeReview();
    closePronCard();
    closePronBook();
    closeA1Path();
    closeRetention();
    closeFeedback();
  });

  // TASK-0052：阅读完成落库——内容超一屏时，滚动到文末自动标记（幂等）
  const readBody = document.getElementById('readBody');
  if(readBody){
    readBody.addEventListener('scroll', function(){
      if(!state.read.currentId) return;
      if(this.scrollHeight <= this.clientHeight + 24) return; // 短文走停留计时，不靠滚动
      if(this.scrollTop + this.clientHeight >= this.scrollHeight - 24){
        markReadComplete(state.read.currentId);
      }
    }, {passive:true});
  }

  // 先健康检查：网络不通即进入离线演示模式
  try {
    const health = await apiRequest('/api/health');
    if(health==null){ setOffline(); }
  }catch(e){
    setOffline();
  }

  if(state.online){
    try {
      const [scenes, cards, profile] = await Promise.all([
        apiRequest('/api/scenes'),
        apiRequest('/api/cards'),
        apiRequest('/api/profile')
      ]);
      state.scenes = Array.isArray(scenes) ? scenes : [];
      state.cards  = Array.isArray(cards)  ? cards  : [];
      state.profile = profile || FALLBACK_PROFILE;
    }catch(e){
      setOffline();
    }
    // TASK-0060 留存数据单独拉取（增益功能，失败不拖垮首屏/不误进离线）
    try { const rt = await apiRequest('/api/retention'); if(rt) state.retention = rt; } catch(e){}
  }

  if(!state.scenes.length){
    setOffline();
    state.scenes = FALLBACK_SCENES.slice();
  }
  if(!state.cards.length) state.cards = buildFallbackCards();
  if(!state.profile) state.profile = FALLBACK_PROFILE;

  renderTop();
  renderScenes();
  renderVocab();
  renderLedger();
  updateReadVocabBadge();
  const firstId = state.scenes[0].id;
  await selectScene(firstId);
  // TASK-0070 v3.0：今日为默认首屏视图，启动即加载三件事/XP/streak（失败由 initToday 降级）
  initToday();
  // 读音规则 P0：静默加载（失败只降级读音入口，不影响上面已完成的界面）
  loadPronData();
  // TASK-0053：首次引导（localStorage 一次性，每步可跳过）
  const obPending = !onboardingSeen();
  maybeShowOnboarding();
  // TASK-0060：留存温和浮层（onboarding 未完成时不抢弹；有「接着上次」才弹）
  if(!obPending) maybeShowRetention();
}

// 发布全部顶层函数到 window：原单文件脚本里 function 声明天然是全局的，
// 内联 onclick="fn()" 依赖此行为，ES module 需显式挂载。
window.a1PathDone = a1PathDone;
window.a1PathFinish = a1PathFinish;
window.a1PathGo = a1PathGo;
window.a1PathNext = a1PathNext;
window.closeA1Path = closeA1Path;
window.openA1Path = openA1Path;
window.achievementCardHTML = achievementCardHTML;
window.answerAssessment = answerAssessment;
window.answerExamChoice = answerExamChoice;
window.apiRequest = apiRequest;
window.applyChatResult = applyChatResult;
window.applyCollectResult = applyCollectResult;
window.applyPronProgressItem = applyPronProgressItem;
window.backExamToPapers = backExamToPapers;
window.browserRecognizeFallback = browserRecognizeFallback;
window.buildAsrContext = buildAsrContext;
window.buildAsrHints = buildAsrHints;
window.buildFallbackCards = buildFallbackCards;
window.buildPronIndex = buildPronIndex;
window.capitalize = capitalize;
window.chatLinkBtnHTML = chatLinkBtnHTML;
window.checkAsr = checkAsr;
window.cleanToken = cleanToken;
window.closeFeedback = closeFeedback;
window.closeOnboarding = closeOnboarding;
window.closePronBook = closePronBook;
window.closePronCard = closePronCard;
window.closePronPopover = closePronPopover;
window.closeRetention = closeRetention;
window.closeReview = closeReview;
window.collectAllWords = collectAllWords;
window.collectReadWord = collectReadWord;
window.dailyGoalsCardHTML = dailyGoalsCardHTML;
window.detailFromFallback = detailFromFallback;
window.detectLinkingPairs = detectLinkingPairs;
window.dismissPronTip = dismissPronTip;
window.doReview = doReview;
window.esc = esc;
window.examAnswerDone = examAnswerDone;
window.examTypeName = examTypeName;
window.fallbackChat = fallbackChat;
window.fallbackSpeak = fallbackSpeak;
window.findRulesForCard = findRulesForCard;
window.fmtNum = fmtNum;
window.gentleReadNote = gentleReadNote;
window.goAssessmentRecommend = goAssessmentRecommend;
window.goOnboardingTarget = goOnboardingTarget;
window.init = init;
window.initAssessment = initAssessment;
window.initExam = initExam;
window.ipaEq = ipaEq;
window.jumpAssessmentLevel = jumpAssessmentLevel;
window.levDistance = levDistance;
window.loadPronData = loadPronData;
window.loadPronDetails = loadPronDetails;
window.loadPronProgress = loadPronProgress;
window.loadPronSummaries = loadPronSummaries;
window.loadReadLevels = loadReadLevels;
window.markReadComplete = markReadComplete;
window.maybeShowOnboarding = maybeShowOnboarding;
window.maybeShowPronTip = maybeShowPronTip;
window.maybeShowRetention = maybeShowRetention;
window.messageHTML = messageHTML;
window.microProgressCardHTML = microProgressCardHTML;
window.nextAssessment = nextAssessment;
window.nextExam = nextExam;
window.normIpa = normIpa;
window.normalizeTurn = normalizeTurn;
window.notify = notify;
window.onExamTextInput = onExamTextInput;
window.onboardingSeen = onboardingSeen;
window.openExamPaper = openExamPaper;
window.openFeedback = openFeedback;
window.openFullFromPop = openFullFromPop;
window.openPronBook = openPronBook;
window.openPronCard = openPronCard;
window.openPronCardForNoRule = openPronCardForNoRule;
window.openReadText = openReadText;
window.openReview = openReview;
window.openWordPopover = openWordPopover;
window.pickMimeType = pickMimeType;
window.playCurrentAudio = playCurrentAudio;
window.postCollect = postCollect;
window.postPronProgress = postPronProgress;
window.prevAssessment = prevAssessment;
window.prevExam = prevExam;
window.pronBadgeHTML = pronBadgeHTML;
window.pronFocusLabel = pronFocusLabel;
window.pronKey = pronKey;
window.pronLearnedTotal = pronLearnedTotal;
window.pronPopOutside = pronPopOutside;
window.pronProgressHTML = pronProgressHTML;
window.pronShadowReset = pronShadowReset;
window.pronShadowSection = pronShadowSection;
window.pronStageOf = pronStageOf;
window.pronTotalRules = pronTotalRules;
window.readOfflineNote = readOfflineNote;
window.recommendNext = recommendNext;
window.renderAssessmentQuestion = renderAssessmentQuestion;
window.renderAssessmentResult = renderAssessmentResult;
window.renderChat = renderChat;
window.renderExamPapers = renderExamPapers;
window.renderExamQuestion = renderExamQuestion;
window.renderExamResult = renderExamResult;
window.renderGrowth = renderGrowth;
window.renderHeader = renderHeader;
window.renderLedger = renderLedger;
window.renderPronBook = renderPronBook;
window.renderPronCard = renderPronCard;
window.renderReadLevels = renderReadLevels;
window.renderReadLines = renderReadLines;
window.renderReadTexts = renderReadTexts;
window.renderReadWords = renderReadWords;
window.renderReviewCard = renderReviewCard;
window.renderRoadmap = renderRoadmap;
window.renderScenes = renderScenes;
window.renderTop = renderTop;
window.renderTries = renderTries;
window.renderVocab = renderVocab;
window.reopenOnboarding = reopenOnboarding;
window.resetChat = resetChat;
window.retentionContinue = retentionContinue;
window.saveExamCurrentText = saveExamCurrentText;
window.sceneCards = sceneCards;
window.scoreShadow = scoreShadow;
window.selectFbCat = selectFbCat;
window.selectReadLevel = selectReadLevel;
window.selectScene = selectScene;
window.sendTyped = sendTyped;
window.sentenceTokensHTML = sentenceTokensHTML;
window.setMicStatus = setMicStatus;
window.setOffline = setOffline;
window.shadowFeedback = shadowFeedback;
window.shadowSelfAssess = shadowSelfAssess;
window.showAssessmentPane = showAssessmentPane;
window.showExamPane = showExamPane;
window.showOnboardingStep = showOnboardingStep;
window.showReadDetail = showReadDetail;
window.skillCardHTML = skillCardHTML;
window.speak = speak;
window.startAssessment = startAssessment;
window.stringSim = stringSim;
window.submitAssessment = submitAssessment;
window.submitExam = submitExam;
window.submitFeedback = submitFeedback;
window.submitUserText = submitUserText;
window.switchPronCard = switchPronCard;
window.switchView = switchView;
window.toggleExamRecord = toggleExamRecord;
window.toggleLinkingInline = toggleLinkingInline;
window.toggleMic = toggleMic;
window.toggleShadowRecord = toggleShadowRecord;
window.transcribeAudio = transcribeAudio;
window.transcribeExamAudio = transcribeExamAudio;
window.transcribeShadowAudio = transcribeShadowAudio;
window.translateTurns = translateTurns;
window.tryIt = tryIt;
window.unlockAudio = unlockAudio;
window.updatePronBookEntry = updatePronBookEntry;
window.updatePronCardProgressUI = updatePronCardProgressUI;
window.updateReadVocabBadge = updateReadVocabBadge;
window.userTurn = userTurn;
window.wordTokensHTML = wordTokensHTML;
window.switchPronCoachView = switchPronCoachView;
// TASK-0071 v3.1 听力磨耳 handlers（集中一块，便于跨车道合并）
window.listenBack = listenBack;
window.listenFinish = listenFinish;
window.listenOpen = listenOpen;
window.listenPickLevel = listenPickLevel;
window.listenPlay = listenPlay;
window.listenPlayAll = listenPlayAll;
window.listenSetSpeed = listenSetSpeed;
window.listenSetVariant = listenSetVariant;
window.listenSubmit = listenSubmit;
window.listenToggleDictation = listenToggleDictation;
window.listenToggleLoop = listenToggleLoop;
window.switchListenView = switchListenView;
window.setPronCoachFocus = setPronCoachFocus;
window.nextPronCoachSentence = nextPronCoachSentence;
window.togglePronCoachRecord = togglePronCoachRecord;
window.initPronCoach = initPronCoach;
window.goTodayTask = goTodayTask;
window.initToday = initToday;

// 顶层副作用（原 app.js 末尾）
document.addEventListener('pointerdown', unlockAudio, {once:false});
document.addEventListener('keydown', unlockAudio, {once:false});
init();
