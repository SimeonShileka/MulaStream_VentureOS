"""Transparent prototype incubation gates, not a regulator or professional certification."""
import re
SPECS=[
(1,1,'Business Foundation','Document the business opportunity and ownership',['Define the problem and solution','Identify founders and ownership','Check applicable registration and banking requirements'],['Business concept note and problem statement','Proposed solution and value proposition','Founder profiles and ownership structure','Business registration documents (where applicable)','Business bank account (where applicable)']),
(2,1,'Market Validation','Find real demand and demonstrate customer interest',['Interview real prospective customers','Research competitors and prices','Test an MVP or pilot'],['Market research report','Target customer profiles','Competitor analysis','Customer interviews or survey findings','MVP or prototype','Evidence of customer demand: sales, pilots or letters of intent']),
(3,1,'Business Model Development','Prove how customers and unit economics work',['Complete a Business Model Canvas','Calculate costs and prices','Model acquisition cost and break-even'],['Completed Business Model Canvas','Revenue model and pricing strategy','Product or service costing','Customer acquisition strategy','Unit economics and break-even analysis']),
(4,1,'Growth Strategy and Operational Readiness','Plan achievable growth and operations',['Set milestones and measurable KPIs','Plan sales and operational delivery','Clarify team roles'],['Three-year growth strategy','Sales and marketing plan','Operational implementation plan','Organisational structure','Growth milestones and KPIs']),
(5,2,'Financial Readiness','Create defendable budgets and forecasts',['Record actuals or state no trading history','Build projections and cash-flow','Test downside scenarios'],['Historical financial statements or management accounts (where available)','Three-to-five-year financial projections','Monthly cash-flow forecast','Operating budget','Funding requirements','Financial sensitivity analysis']),
(6,2,'Governance, Legal and Compliance','Identify statutory requirements and controls',['Check sector-specific permits','Document ownership and contracts','Establish key controls'],['Company registration and statutory documents','Tax registration and compliance documentation','Required licences and permits','Shareholder agreements (where applicable)','Key business contracts','Governance and internal control policies']),
(7,2,'Investment Structuring and Capital Readiness','Build a coherent and transparent funding proposition',['Specify funding amount and use','Compare debt and equity','Model repayment or equity scenarios'],['Investment proposal','Funding amount and use-of-funds schedule','Appropriate financing structure: debt or equity','Business valuation (where applicable)','Debt repayment plan or equity return scenarios','Investment milestones']),
(8,3,'Due Diligence and Investor Engagement','Prepare the investor package and practise scrutiny',['Compile supporting documents','Prepare pitch and Q&A','Run a mock investment committee'],['Investor pitch deck','Executive investment summary','Investment memorandum','Complete due diligence data room','Final financial model','Investor Q&A document','Mock investment committee presentation','Investment readiness assessment and score','Fundraising and investor engagement plan'])]
STAGES=[dict(number=n,month=m,title=t,goal=g,activities=a,deliverables=d) for n,m,t,g,a,d in SPECS]
def roadmap(venture):
    return [dict(month=m,name=name,goal=goal) for m,name,goal in [(1,'Foundation and commercial validation','Validated model, evidence of demand and credible growth strategy'),(2,'Financial, governance and capital readiness','Credible financial position, controls and clearly stated investment opportunity'),(3,'Due diligence and investor engagement','Investor dossier, assessed readiness and fundraising plan')]]
def assess(stage,deliverable,text,ref):
    words=re.findall(r'\b\w+\b',text)
    # Scores measure draft completeness and specificity only; never claim factual verification.
    score=10
    if len(words)>=35:score+=20
    if len(words)>=90:score+=15
    if len(words)>=170:score+=10
    if re.search(r'\b\d+(?:[.,]\d+)?\b',text):score+=10
    if re.search(r'\b(customer|date|month|sales|cost|budget|revenue|supplier|competitor|survey|interview|assumption|risk|owner|target|kpi)\b',text,re.I):score+=10
    if ref:score+=10
    if re.search(r'\b(evidence|sample|receipt|statement|interview|contract|source|invoice|reference)\b',text,re.I):score+=5
    if len(set(w.lower() for w in words))<max(8,len(words)//5):score=min(score,40)
    score=min(90,score)
    issues=[]
    if len(words)<90:issues.append('Add detail about methods, results and next actions')
    if not re.search(r'\b\d+\b',text):issues.append('Add measurable figures, dates or quantities where appropriate')
    if not ref:issues.append('Add a traceable evidence reference if available')
    issues.append('A qualified reviewer must confirm authenticity, accuracy and stage progression')
    return {'score':score,'feedback':'; '.join(issues),'standard':'Draft completeness only; not an AI verification of facts'}
