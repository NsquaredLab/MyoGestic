% Example script for direct communication with Muovi
%
% This script builds the communication command starting from the values
% of few variables, open a socket for the connection of Muovi and, when the
% Muovi is connected, sends the command and starts receiving data
%
% OT Bioelettronica
% v. 3.0

close all
clear all

% Initialization
TCPPort = 54321; % Number of TCP socket port
NumCycles = 20;  % Number of recording cycles
OffsetEMG = 1;   % Offset between the channels' signals 
PlotTime = 1;    
OnlyEMG = 0;

% -------------------------------------------------------------------------
% Refer to the communication protocol for details about these variables:
ProbeEN = 1;    % 1 = Probe enabled, 0 = probe disabled
EMG = 1;        % 1 = EMG, 0 = EEG
Mode = 0;       % 0 = 32Ch Monop, 1 = 16Ch Monop, 2 = 32Ch ImpCk, 3 = 32Ch Test

% Conversion factor for the bioelectrical signals to get the values in mV
ConvFact = 0.000286;

% Number of acquired channel depending on the acquisition mode
NumChanVsMode = [38 22 38 38];

% Prevents error of the user in the variables' initialization
if ProbeEN > 1
    disp("Error, set ProbeEN values equal to 0 or 1")
    return;
end

if EMG > 1
    disp("Error, set EMGX values equal to 0 or 1")
    return;
end

if Mode > 7
    disp("Error, set ModeX values between 0 and 7")
    return;
end

% Create the command to send to Muovi
Command = 0;
if ProbeEN == 1
    Command = 0 + EMG * 8 + Mode * 2 + 1;
    NumChan = NumChanVsMode(Mode+1);
    if EMG == 0
        sampFreq = 500;   % Sampling frequency = 500 for EEG
    else
        sampFreq = 2000;  % Sampling frequency = 2000 for EMG
    end
end

% Conversion from decimal integer to its binary representation
dec2bin(Command)

% The function tcpip is substituted by the functions
% tcpserver/tcpclient from Matlab version 2022a

if verLessThan('matlab','9.12')
    % Open the TCP socket as server
    t = tcpip('0.0.0.0', TCPPort, 'NetworkRole', 'server');
    % Increase the input buffer size
    t.InputBufferSize = 500000; %190152;
    % Wait into this function until a client is connected
    fopen(t)
else
    % Open the TCP socket as server
    t = tcpserver(TCPPort,"ByteOrder","big-endian");
    % Increase the input buffer size
    t.InputBufferSize = 500000; %190152;
    % Wait into this function until a client is connected
    fopen(t)
    while(t.Connected < 1)
       pause(0.1)
    end
end

disp('Connected to the Socket')

if OnlyEMG == 1 
    EMG = plot(0);
    xlim([0 sampFreq])
    ylim([-OffsetEMG (OffsetEMG*(NumChan-6))])
else
    subplot(3,1,1)
    EMG = plot(0);
    xlim([0 sampFreq])
    ylim([-OffsetEMG (OffsetEMG*(NumChan-6))])

    subplot(3,1,2)
    IMU = plot(0);
    xlim([0 sampFreq])
    ylim([-33000 33000])

    subplot(3,3,7)
    Buf = plot(0);
    xlim([0 sampFreq])
    ylim([0 16000])

    subplot(3,3,8)
    Trig = plot(0);
    xlim([0 sampFreq])
    ylim([0 1.1])

    subplot(3,3,9)
    Ramp = plot(0);
    xlim([0 sampFreq])
    ylim([-33000 33000])
end

% Send the command to Muovi
fwrite(t, Command, 'uint8');

if ProbeEN == 0
    % Wait to be sure the command is received before closing the socket
    pause(0.5);
    clear t;
end

% If the high resolution mode (24 bits) is active
if(EMG == 0)
    % One second of data: 3 bytes * channels * Sampling frequency
    blockData = 3*NumChan*sampFreq;
    
    ChInd = (1:3:NumChan*3);
    
    % Main plot loop
    for i = 1 : NumCycles
        
        i
        
        % Wait here until one second of data has been received
        while(t.BytesAvailable < blockData)
        end
        
        % Read one second of data into single bytes
        Temp = fread(t, NumChan*3*sampFreq, 'uint8');
        Temp1 = reshape(Temp, NumChan*3, sampFreq);

        % Combine 3 bytes to a 24 bit value
        data{i} = Temp1(ChInd,:)*65536 + Temp1(ChInd+1,:)*256 + Temp1(ChInd+2,:);
        
        % Search for the negative values and make the two's complement
        ind = find(data{i} >= 8388608);
        data{i}(ind) = data{i}(ind) - (16777216);
        
        % Plot the EEG signals
        subplot(3,1,1)
        % Plot the data received
        hold off
        for j = 1 : NumChan-6
            plot(data{i}(j,:)*ConvFact + 0.1*(j-1));
            hold on
        end
        
        % Plot the IMU
        subplot(3,1,2)
        hold off
        for j = NumChan-5 : NumChan-2
            %set(IMU, 'YData', data{i}(j,:));
            plot(data{i}(j,:))
            hold on
        end

%         subplot(2,1,2)
%         plot(rem((data{i}(NumChan-1,:)), 16384)*8);
%         drawnow;
        
        ind = find(data{i}(NumChan-1,:) < 0);
        Trigger = zeros(sampFreq, 1);
        Trigger(ind) = 1;
        Buffer = data{i}(NumChan-1,:);
        Buffer(ind) = data{i}(NumChan-1,ind) + 32768;

        subplot(3,3,7)
        set(Buf, 'YData', Buffer);

        subplot(3,3,8)
        set(Trig, 'YData', Trigger);

        subplot(3,3,9)
        set(Ramp, 'YData', data{i}(NumChan,:));

        drawnow;
    end
else

    % If the low resolution mode (16 bits) is active
    
    % One second of data: 2 bytes * channels * Sampling frequency
    blockData = 2*NumChan*sampFreq;
    
    % Main plot loop
    for i = 1 : NumCycles
        
        i
        
        % Wait here until one second of data has been received
        while(t.BytesAvailable < blockData)
        end
        
        % Read one second of data into signed integer
        Temp = fread(t, NumChan*sampFreq, 'int16');
        data{i} = reshape(Temp, NumChan, sampFreq);

        if OnlyEMG == 1
            hold off
            for j = 1 : NumChan-6
                %set(EMG, 'YData', data{i}(j,:)*ConvFact + OffsetEMG*(j-1));
                plot(data{i}(j,:)*ConvFact + OffsetEMG*(j-1))
                hold on
            end
        else
            % Plot the EMG signals
            subplot(3,1,1)
            hold off
            for j = 1 : NumChan-6
                %set(EMG, 'YData', data{i}(j,:)*ConvFact + OffsetEMG*(j-1));
                plot(data{i}(j,:)*ConvFact + OffsetEMG*(j-1))
                hold on
            end

            % Plot the IMU
            subplot(3,1,2)
            hold off
            for j = NumChan-5 : NumChan-2
                %set(IMU, 'YData', data{i}(j,:));
                plot(data{i}(j,:))
                hold on
            end

            ind = find(data{i}(NumChan-1,:) < 0);
            Trigger = zeros(sampFreq, 1);
            Trigger(ind) = 1;
            Buffer = data{i}(NumChan-1,:);
            Buffer(ind) = data{i}(NumChan-1,ind) + 32768;

            subplot(3,3,7)
            set(Buf, 'YData', Buffer);

            subplot(3,3,8)
            set(Trig, 'YData', Trigger);

            subplot(3,3,9)
            set(Ramp, 'YData', data{i}(NumChan,:));
        end

        drawnow;
    end
end

% Stop the data transfer
fwrite(t, Command-1, 'uint8');

% Wait to be sure the command is received before closing the socket
pause(0.5);

% Close the TCP socket
clear t

