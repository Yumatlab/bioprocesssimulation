function [dy] = Pichia_Induction_Cornelissen(qXpX,qS2pXind,aS2script,aS2trans,aS2act,bS2script,bS2trans,bS2act,t,y)
% y0 = [qS2pXscript0, qS2pXtrans0, qS2pXact0]
% Transcription
dy(1) = -(aS2script+qXpX)*y(1)+bS2script*qS2pXind;
% Translation
dy(2) = -(aS2trans+qXpX)*y(2)+bS2trans*y(1);
% Activity
dy(3) = -(aS2act+qXpX)*y(3)+bS2act*y(2);
dy = dy';
end