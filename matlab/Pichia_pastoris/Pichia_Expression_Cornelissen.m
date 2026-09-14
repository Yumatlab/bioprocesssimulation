function [dy] = Pichia_Expression_Cornelissen(qXpX,qP1pXind,qP1pXback,aP1script,aP1trans,kP1alpha,bP1script,bP1trans,bP1act,t,y)   
    % y0 = [qP1pXscript, qP1pXtrans, qP1pXact]
    % Transcription
    dy(1) = -(aP1script + qXpX) * y(1) + bP1script * (qP1pXind + qP1pXback);
    % Translation
    dy(2) = -(aP1trans + qXpX) * y(2) + bP1trans * y(1);
    % Activity
    dy(3) = -(kP1alpha + qXpX) * y(3) + bP1act * y(2);
    
    dy = dy';
end