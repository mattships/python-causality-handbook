--[[
Index terms for the book, used by book.lua.

  entry     the index entry as makeindex sees it ("sort key@Display")
  patterns  lowercase prefixes to look for in running text; a match must
            start at a word boundary ("confound" finds "confounders")
  acronyms  case-sensitive whole words ("ATE", "2SLS")
  home      chapters about the term: indexed as one page range there
  exclude   longer phrases that belong to another entry

Outside its home chapters a term is indexed at its first mention in each
chapter, which is where a reader looking it up wants to land.

Paragraphs inside "References" sections are not indexed.
]]

return {
  -- foundations -------------------------------------------------------------
  {entry = 'potential outcomes', patterns = {'potential outcome'}, home = {'ch01'}},
  {entry = 'counterfactual', patterns = {'counterfactual'}},
  {entry = 'fundamental problem of causal inference', patterns = {'fundamental problem of causal inference'}},
  {entry = 'average treatment effect (ATE)', patterns = {'average treatment effect'}, acronyms = {'ATE'},
   home = {'ch01'},
   exclude = {'average treatment effect on the treated'}},
  {entry = 'average treatment effect on the treated (ATT)', patterns = {'average treatment effect on the treated'},
   acronyms = {'ATT'}},
  {entry = 'conditional average treatment effect (CATE)', patterns = {'conditional average treatment effect'},
   acronyms = {'CATE'}, home = {'ch18'}},
  {entry = 'individual treatment effect', patterns = {'individual treatment effect'}},
  {entry = 'association and causation', patterns = {'association is not causation', 'association be causation',
   'association is causation', 'association and causation'}},
  {entry = 'bias!selection', patterns = {'selection bias'}},
  {entry = 'bias!omitted variable', patterns = {'omitted variable bias'}},
  {entry = 'bias!confounding', patterns = {'confounding bias'}},
  {entry = 'confounding', patterns = {'confounder', 'confounding'}, exclude = {'confounding bias'}},
  {entry = 'randomized controlled trial (RCT)', patterns = {'randomised controlled trial', 'randomized controlled trial',
   'randomised experiment', 'randomized experiment', 'random experiment'}, acronyms = {'RCT', 'RCTs'},
   home = {'ch02'}},
  {entry = 'A/B test', patterns = {'a/b test'}},
  {entry = 'conditional independence', patterns = {'conditional independence', 'unconfoundedness'}},
  {entry = 'positivity', patterns = {'positivity'}},
  {entry = 'exchangeability', patterns = {'exchangeab'}},

  -- statistics ---------------------------------------------------------------
  {entry = 'standard error', patterns = {'standard error'}, home = {'ch03'}},
  {entry = 'confidence interval', patterns = {'confidence interval'}, home = {'ch03'}},
  {entry = 'p-value', patterns = {'p-value'}, home = {'ch03'}},
  {entry = 'hypothesis testing', patterns = {'hypothesis test'}},
  {entry = 'central limit theorem', patterns = {'central limit theorem'}},
  {entry = "Moivre's equation", patterns = {'moivre'}},
  {entry = 'bootstrap', patterns = {'bootstrap'}},

  -- graphs -------------------------------------------------------------------
  {entry = 'causal graphs', patterns = {'causal graph', 'graphical model', 'graphical causal model'},
   home = {'ch04'}},
  {entry = 'collider', patterns = {'collider'}},
  {entry = 'backdoor path', patterns = {'backdoor'}},
  {entry = 'mediator', patterns = {'mediator'}},
  {entry = 'controls, good and bad', patterns = {'bad control', 'good control', 'harmful control'}, home = {'ch07'}},

  -- regression ---------------------------------------------------------------
  {entry = 'linear regression', patterns = {'linear regression'}, home = {'ch05', 'ch06'}},
  {entry = 'ordinary least squares (OLS)', patterns = {'ordinary least squares'}, acronyms = {'OLS'}},
  {entry = 'Frisch-Waugh-Lovell theorem@Frisch--Waugh--Lovell theorem', patterns = {'frisch'}, acronyms = {'FWL'}},
  {entry = 'dummy variables', patterns = {'dummy variable', 'dummies'}, home = {'ch06'}},
  {entry = 'heteroskedasticity', patterns = {'heteroskedastic', 'heteroscedastic'}},
  {entry = 'fixed effects', patterns = {'fixed effect'}, home = {'ch14'}, exclude = {'two way fixed effect',
   'two-way fixed effect'}},
  {entry = 'panel data', patterns = {'panel data'}, home = {'ch14'}},
  {entry = 'logistic regression', patterns = {'logistic regression'}},

  -- instruments --------------------------------------------------------------
  {entry = 'instrumental variables (IV)', patterns = {'instrumental variable'}, acronyms = {'IV', 'IVs'},
   home = {'ch08', 'ch09'}},
  {entry = 'two-stage least squares (2SLS)', patterns = {'two stage least squares', 'two-stage least squares'},
   acronyms = {'2SLS'}, home = {'ch08'}},
  {entry = 'first stage', patterns = {'first stage', 'first-stage'}},
  {entry = 'reduced form', patterns = {'reduced form'}},
  {entry = 'exclusion restriction', patterns = {'exclusion restriction'}},
  {entry = 'quarter of birth', patterns = {'quarter of birth'}},
  {entry = 'local average treatment effect (LATE)', patterns = {'local average treatment effect'},
   acronyms = {'LATE'}, home = {'ch09'}},
  {entry = 'non-compliance', patterns = {'non compliance', 'non-compliance', 'noncompliance'}, home = {'ch09'}},
  {entry = 'compliers', patterns = {'complier'}},
  {entry = 'always takers', patterns = {'always taker', 'always-taker'}},
  {entry = 'never takers', patterns = {'never taker', 'never-taker'}},
  {entry = 'defiers', patterns = {'defier'}},
  {entry = 'monotonicity', patterns = {'monotonicity'}},

  -- matching and propensity --------------------------------------------------
  {entry = 'matching', patterns = {'matching estimator', 'matching'}, home = {'ch10'}},
  {entry = 'nearest neighbours', patterns = {'nearest neighbo'}, acronyms = {'KNN'}},
  {entry = 'curse of dimensionality', patterns = {'curse of dimensionality'}},
  {entry = 'subclassification', patterns = {'subclassification'}},
  {entry = 'propensity score', patterns = {'propensity score'}, home = {'ch11', 'appB'}},
  {entry = 'propensity weighting', patterns = {'propensity weighting', 'inverse propensity', 'inverse probability weighting'},
   acronyms = {'IPW'}},
  {entry = 'doubly robust estimation', patterns = {'doubly robust'}, home = {'ch12'}},

  -- differences in time ------------------------------------------------------
  {entry = 'difference-in-differences', patterns = {'difference-in-differences', 'diff-in-diff',
   'difference in differences', 'differences-in-differences'}, home = {'ch13', 'ch24'},
   exclude = {'synthetic difference-in-differences', 'synthetic diff-in-diff'}},
  {entry = 'parallel trends', patterns = {'parallel trend'}},
  {entry = 'two-way fixed effects (TWFE)', patterns = {'two way fixed effect', 'two-way fixed effect'},
   acronyms = {'TWFE'}, home = {'ch24'}},
  {entry = 'staggered adoption', patterns = {'staggered'}},
  {entry = 'event study', patterns = {'event study', 'event-study'}},
  {entry = 'synthetic control', patterns = {'synthetic control'}, home = {'ch15', 'appE'}},
  {entry = 'synthetic difference-in-differences (SDID)', patterns = {'synthetic difference-in-differences',
   'synthetic diff-in-diff', 'synthetic difference in differences'}, acronyms = {'SDID'}, home = {'ch25'}},
  {entry = 'donor pool', patterns = {'donor pool'}},
  {entry = 'placebo test', patterns = {'placebo'}},
  {entry = 'permutation test', patterns = {'permutation'}},
  {entry = 'Proposition 99', patterns = {'proposition 99'}},
  {entry = 'conformal inference', patterns = {'conformal'}, home = {'appE'}},

  -- regression discontinuity -------------------------------------------------
  {entry = 'regression discontinuity design (RDD)', patterns = {'regression discontinuity'},
   acronyms = {'RDD', 'RD'}, home = {'ch16'}},
  {entry = 'running variable', patterns = {'running variable'}},
  {entry = 'kernel weighting', patterns = {'kernel'}},
  {entry = 'sheepskin effect', patterns = {'sheepskin'}},
  {entry = 'bunching', patterns = {'bunching'}},

  -- heterogeneity and machine learning -------------------------------------
  {entry = 'cross-validation', patterns = {'cross validation', 'cross-validation'}},
  {entry = 'overfitting', patterns = {'overfit'}},
  {entry = 'regularization', patterns = {'regulariz', 'regularis'}},
  {entry = 'decision trees', patterns = {'decision tree'}},
  {entry = 'heterogeneous treatment effects', patterns = {'heterogeneous treatment effect', 'effect heterogeneity'},
   home = {'ch18', 'ch23'}},
  {entry = 'personalization', patterns = {'personaliz', 'personalis'}},
  {entry = 'elasticity', patterns = {'elasticit'}},
  {entry = 'cumulative gain curve', patterns = {'cumulative gain'}, home = {'ch19'}},
  {entry = 'cumulative sensitivity curve', patterns = {'cumulative sensitivity', 'cumulative elasticity'}, home = {'ch19'}},
  {entry = 'target transformation', patterns = {'target transformation'}, home = {'ch20'}},
  {entry = 'meta-learners', patterns = {'meta learner', 'meta-learner'}, home = {'ch21'}},
  {entry = 'meta-learners!S-learner', patterns = {'s-learner', 's learner'}},
  {entry = 'meta-learners!T-learner', patterns = {'t-learner', 't learner'}},
  {entry = 'meta-learners!X-learner', patterns = {'x-learner', 'x learner'}},
  {entry = 'double/debiased machine learning', patterns = {'double/debiased', 'debiased/orthogonal', 'debiased ml',
   'debiased machine learning', 'double machine learning', 'double ml'}, home = {'ch22'}},
  {entry = 'orthogonalization', patterns = {'orthogonaliz', 'orthogonalis', 'orthogonal ml',
   'orthogonal machine learning'}, home = {'appA'}},
  {entry = 'R-learner', patterns = {'r-learner', 'r-loss'}},
}
