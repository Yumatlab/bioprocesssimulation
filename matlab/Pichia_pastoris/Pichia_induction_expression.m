clear all

% Pichia model
%% AOX induction

kappaind = 6;
kapparep = 4;
kS2ind = 0.001; % g/l 
kS1rep = 0.00162; % g/l
qS2pXsup = 0.3303; % 1/h

qS2pXscript0 = 0.3;
qS2pXtrans0 = 0.3;
qS2pXact0 = 0.2;

mu3max = 0.05; % Mut+ stemm Discussion part
aS2script = 76.6;
bS2script = aS2script + mu3max;

aS2trans = 5.463; % 1/h
bS2trans = aS2trans + mu3max;

aS2act = 0.1348; % 1/h
bS2act = aS2act + mu3max;

qXpX = 0.02; % 1/h

kI22 = 21.29; % g/l
KS2ind = 0.001; % g/l
kS2 = 0.7429; % g/l
kI21 = 0.01233; % g/l
cS2Lopt = sqrt(kS2*kI22); % g/l
qS2pXmax = qS2pXsup*(cS2Lopt/(kS2+cS2Lopt))*(kI22/(kI22+cS2Lopt)); % 1/h
deltat = 0.00056; % h
%deltat = 0.000001; % h

time = 0:0.01:10;
% Substrate concentration
%%%%%%%%%%%%%%%%
cS2L = 2;
cS1L = 20;
%%%%%%%%%%%%%%%%

% Turn on/turn Off functions
VS2ind = ((cS2L/kS2ind)^kappaind)/(1+(cS2L./kS2ind)^kappaind);
VS1rep = 1/(1+(cS1L/kS1rep)^kapparep);

qS2pXind = VS1rep.*VS2ind.*qS2pXsup;

function [dy] = Pichia_induction_Cornelissen(qXpX,qS2pXind,aS2script,aS2trans,aS2act,bS2script,bS2trans,bS2act,t,y)
% y0 = [qS2pXscript, qS2pXtrans, qS2pXact]
% Transcription
dy(1) = -(aS2script+qXpX)*y(1)+bS2script*qS2pXind;
% Translation
dy(2) = -(aS2trans+qXpX)*y(2)+bS2trans*y(1);
% Activity
dy(3) = -(aS2act+qXpX)*y(3)+bS2act*y(2);

dy = dy';
end

ODE_Induction = @(t,y) Pichia_induction_Cornelissen(qXpX,qS2pXind,aS2script,aS2trans,aS2act,bS2script,bS2trans,bS2act,t,y);
[~,y] = ode45(ODE_Induction,[0 deltat],[qS2pXscript0, qS2pXtrans0, qS2pXact0]);

qS2pXscript = y(end,1);
qS2pXtrans = y(end,2);
qS2pXact = y(end,3);

qS2pX = qS2pXact*(cS2L/(kS2+cS2L))*(kI22/(kI22+cS2L))*(kI21/(kI21+cS1L));

%% Target protein expression

KCP1script = 0.3106; % -
aP1script = 104.0;
bP1script = aP1script + mu3max;

aP1trans = 15.04; % 1/h
bP1trans = aP1trans + mu3max;

kP1alpha = 19.58; % 1/h
bP1act = kP1alpha + mu3max; % ???

qP1pXsup = 51.39*10^-6; % g/(gh)
qP1pXmax = 10.73*10^-6; % g/(gh)
TIP1script = 5.367; % h

qP1pXscript0 = 10.73*10^-6;
qP1pXtrans0 = 10.73*10^-6;
qP1pXact0 = 10.73*10^-6;

% Turn on/turn Off functions
VS2ind = ((cS2L/kS2ind)^kappaind)/(1+(cS2L/kS2ind)^kappaind);
VS1rep = 1/(1+(cS1L/kS1rep)^kapparep);

qP1pXind = VS1rep*VS2ind*qP1pXsup;

qP1pXscriptw = VS1rep*VS2ind*qP1pXmax;

% % function [dy] = Pichia_expression_Cornelissen(qP1pXscriptw,KCP1script,TIP1script,qXpX,qP1pXind,aP1script,aP1trans,kP1alpha,bP1script,bP1trans,bP1act,t,y)
% % % y0 = [qP1pXscript, qP1pXtrans, qP1pXact]
% % % deltaqP1pXscript = (qP1pXscriptw-y(1));
% % % qP1pXback = KCP1script*(deltaqP1pXscript+1/TIP1script*(integral(deltaqP1pXscript,t(1),t(end))));
% % % Transcription
% % dy(1) = -(aP1script+qXpX)*y(1)+bP1script*(qP1pXind+KCP1script*((qP1pXscriptw-y(1))+1/TIP1script*(integral((qP1pXscriptw-y(1)),t(1),t(end)))));
% % % Translation
% % dy(2) = -(aP1trans+qXpX)*y(2)+bP1trans*y(1);
% % % Activity
% % dy(3) = -(kP1alpha+qXpX)*y(3)+bP1act*y(2);
% % 
% % dy = dy';
% % end
% % 
% % ODE_Expression = @(t,y) Pichia_expression_Cornelissen(qP1pXscriptw,KCP1script,TIP1script,qXpX,qP1pXind,aP1script,aP1trans,kP1alpha,bP1script,bP1trans,bP1act,t,y);
% % [~,y] = ode45(ODE_Expression,[0 deltat],[qP1pXscript0, qP1pXtrans0, qP1pXact0]);

delta_qP1pXscript = qP1pXscriptw - y(1); % Calculate control deviation
qP1pXback = KCP1script*(delta_qP1pXscript+integral())
function [dy] = Pichia_expression_Cornelissen(qP1pXscriptw,KCP1script,TIP1script,qXpX,qP1pXind,aP1script,aP1trans,kP1alpha,bP1script,bP1trans,bP1act,t,y)
    % y0 = [qP1pXscript, qP1pXtrans, qP1pXact, integ_value]

    

    % Transcription
    dy(1) = -(aP1script + qXpX) * y(1) + bP1script * (qP1pXind + KCP1script * (delta_qP1pXscript + y(4)/TIP1script));

    % Translation
    dy(2) = -(aP1trans + qXpX) * y(2) + bP1trans * y(1);

    % Activity
    dy(3) = -(kP1alpha + qXpX) * y(3) + bP1act * y(2);

    % Calculate change of integral
    dy(4) = delta_qP1pXscript;

    dy = dy';
end
% 
ODE_Expression = @(t,y) Pichia_expression_Cornelissen(qP1pXscriptw,KCP1script,TIP1script,qXpX,qP1pXind,aP1script,aP1trans,kP1alpha,bP1script,bP1trans,bP1act,t,y);

% IVP
[~,y] = ode45(ODE_Expression, [0 deltat], [qP1pXscript0, qP1pXtrans0, qP1pXact0, qP1pXscriptw]);

qP1pXscript = y(end, 1);
qP1pXtrans = y(end, 2);
qP1pXact = y(end, 3);

qP1pX = qP1pXact;
